"""Tests for dependency-specific readiness checks."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from quiz_api.web.readiness import check_readiness


class FakeSession:
    """Accept the small readiness query without a real PostgreSQL connection."""

    async def execute(self, _: object) -> None:
        """Record a successful SQL readiness probe."""


class FailingSession(FakeSession):
    """Simulate an unavailable PostgreSQL dependency."""

    async def execute(self, _: object) -> None:
        """Fail the readiness query."""
        message = "database unavailable"
        raise ConnectionError(message)


class FakeRedis:
    """Return a configured Redis ping result."""

    def __init__(self, *, available: bool) -> None:
        """Store whether the fake Redis dependency is available."""
        self._available = available

    async def ping(self) -> bool:
        """Return the configured readiness state."""
        if not self._available:
            message = "redis unavailable"
            raise ConnectionError(message)
        return True


class FakeResources:
    """Expose only the readiness dependencies required by the probe."""

    def __init__(self, session: FakeSession, redis: FakeRedis) -> None:
        """Store the database session context and Redis client."""
        self.redis = redis
        self.session_factory = make_session_factory(session)


def make_session_factory(session: FakeSession) -> object:
    """Build an async session-factory-shaped callable around the supplied fake session."""

    @asynccontextmanager
    async def session_context() -> AsyncIterator[FakeSession]:
        yield session

    return session_context


async def test_readiness_reports_each_dependency_when_all_are_available() -> None:
    """Both dependencies are visible as healthy to a load balancer."""
    result = await check_readiness(FakeResources(FakeSession(), FakeRedis(available=True)))  # type: ignore[arg-type]

    assert result.database_ready
    assert result.redis_ready
    assert result.ready


async def test_readiness_distinguishes_database_and_redis_failures() -> None:
    """Operators can tell which backing dependency made the process unready."""
    database_down = await check_readiness(
        FakeResources(FailingSession(), FakeRedis(available=True))  # type: ignore[arg-type]
    )
    redis_down = await check_readiness(
        FakeResources(FakeSession(), FakeRedis(available=False))  # type: ignore[arg-type]
    )

    assert not database_down.database_ready
    assert database_down.redis_ready
    assert not redis_down.redis_ready
    assert redis_down.database_ready
