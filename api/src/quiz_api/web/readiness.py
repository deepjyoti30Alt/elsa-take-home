"""Database and Redis readiness checks for load balancers and deployments."""

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.observability import DEPENDENCY_FAILURES


class ReadinessSessionFactory(Protocol):
    """Create asynchronous database-session contexts for readiness checks."""

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        """Return an asynchronous context manager yielding a database session."""


class ReadinessRedis(Protocol):
    """Redis command subset used by the readiness probe."""

    async def ping(self) -> bool:
        """Return whether Redis accepted a ping command."""


class ReadinessResources(Protocol):
    """Application resources required by the readiness probe."""

    redis: ReadinessRedis
    session_factory: ReadinessSessionFactory


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    """Independently reported database and Redis availability state."""

    database_ready: bool
    redis_ready: bool

    @property
    def ready(self) -> bool:
        """Return whether every dependency required for live delivery is healthy."""
        return self.database_ready and self.redis_ready


async def check_readiness(resources: ReadinessResources) -> ReadinessResult:
    """Check database and Redis concurrently without exposing dependency error details."""
    database_ready, redis_ready = await asyncio.gather(
        check_database(resources.session_factory),
        check_redis(resources.redis),
    )
    return ReadinessResult(database_ready=database_ready, redis_ready=redis_ready)


async def check_database(session_factory: ReadinessSessionFactory) -> bool:
    """Execute a small database query and record only its aggregate failure signal."""
    try:
        session_context = session_factory()
        async with session_context as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        DEPENDENCY_FAILURES.labels(dependency="database").inc()
        return False
    return True


async def check_redis(redis: ReadinessRedis) -> bool:
    """Ping Redis and record only its aggregate failure signal."""
    try:
        return await redis.ping()
    except Exception:
        DEPENDENCY_FAILURES.labels(dependency="redis").inc()
        return False
