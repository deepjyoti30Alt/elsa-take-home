"""Application-owned connections and background worker lifecycle."""

from asyncio import Task, create_task, gather
from collections.abc import Awaitable
from dataclasses import dataclass, field

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from quiz_api.settings import Settings


@dataclass(slots=True)
class BackgroundWorkers:
    """Own tasks that run alongside the API process."""

    tasks: set[Task[None]] = field(default_factory=set)

    def start(self, worker: Awaitable[None]) -> None:
        """Start a worker and retain it for graceful shutdown."""
        task: Task[None] = create_task(await_worker(worker))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def stop(self) -> None:
        """Cancel active workers and wait for their cleanup to complete."""
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await gather(*self.tasks, return_exceptions=True)


async def await_worker(worker: Awaitable[None]) -> None:
    """Adapt a general awaitable to the coroutine required by create_task."""
    await worker


@dataclass(slots=True)
class ApplicationResources:
    """Connections and worker ownership for one FastAPI process."""

    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    workers: BackgroundWorkers

    async def close(self) -> None:
        """Release resources in reverse dependency order."""
        await self.workers.stop()
        await self.redis.aclose()
        await self.engine.dispose()


def create_application_resources(settings: Settings) -> ApplicationResources:
    """Create clients and factories without performing network I/O."""
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return ApplicationResources(
        engine=engine,
        session_factory=session_factory,
        redis=redis,
        workers=BackgroundWorkers(),
    )
