"""Tests for Redis leaderboard reads and safe cache degradation."""

from uuid import UUID

from quiz_api.services.leaderboard_cache import RedisLeaderboardReader
from quiz_api.services.outbox_relay import (
    leaderboard_key,
    leaderboard_names_key,
    leaderboard_totals_key,
)

QUIZ_ID = UUID("10000000-0000-0000-0000-000000000001")
PARTICIPANT_ID = UUID("20000000-0000-0000-0000-000000000002")


class FakeRedis:
    """Provide enough projected Redis state to exercise cache reads."""

    async def exists(self, *_: str) -> int:
        """Report that the leaderboard sorted set exists."""
        return 1

    async def zrange(self, *_: object) -> list[str]:
        """Return one ranked participant from the sorted set."""
        return [str(PARTICIPANT_ID)]

    async def hgetall(self, key: str) -> dict[str, str]:
        """Return the names or exact totals sidecar hash."""
        if key == leaderboard_names_key(QUIZ_ID):
            return {str(PARTICIPANT_ID): "Ada"}
        if key == leaderboard_totals_key(QUIZ_ID):
            return {str(PARTICIPANT_ID): '{"total_response_ms":300,"total_score":195}'}
        return {}

    async def zcard(self, *_: str) -> int:
        """Return the total number of cached participants."""
        return 1


class UnavailableRedis(FakeRedis):
    """Simulate a Redis connection failure while preserving the same interface."""

    async def exists(self, *_: str) -> int:
        """Fail the initial cache health/read operation."""
        message = "Redis is unavailable"
        raise ConnectionError(message)


async def test_redis_reader_returns_the_same_ranked_contract_as_postgresql() -> None:
    """A complete cache projection is safe for the public leaderboard endpoint."""
    page = await RedisLeaderboardReader(FakeRedis()).get_page(
        quiz_id=QUIZ_ID,
        limit=50,
        offset=0,
    )

    assert page is not None
    assert page.total == 1
    assert page.entries[0].display_name == "Ada"
    assert page.entries[0].total_score == 195


async def test_redis_reader_returns_none_when_the_cache_is_unavailable() -> None:
    """The service can use PostgreSQL when Redis raises during a cache read."""
    page = await RedisLeaderboardReader(UnavailableRedis()).get_page(
        quiz_id=QUIZ_ID,
        limit=50,
        offset=0,
    )

    assert page is None


def test_redis_projection_keys_are_quiz_scoped() -> None:
    """Names, totals, and ordering state remain isolated for each quiz ID."""
    assert leaderboard_key(QUIZ_ID).startswith(f"quiz:{QUIZ_ID}:")
    assert leaderboard_names_key(QUIZ_ID).startswith(f"quiz:{QUIZ_ID}:")
    assert leaderboard_totals_key(QUIZ_ID).startswith(f"quiz:{QUIZ_ID}:")
