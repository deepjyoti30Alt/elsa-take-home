"""Redis-backed leaderboard reads that degrade safely to PostgreSQL."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from quiz_api.services.leaderboard import RankedStanding
from quiz_api.services.outbox_relay import (
    RedisEventTransport,
    leaderboard_key,
    leaderboard_names_key,
    leaderboard_totals_key,
)

if TYPE_CHECKING:
    from quiz_api.services.leaderboard_reads import LeaderboardPage


class RedisLeaderboardReadTransport(RedisEventTransport, Protocol):
    """Additional Redis commands used by the cache-backed leaderboard reader."""

    def exists(self, *names: str) -> Awaitable[int]:
        """Return how many of the requested keys are present."""

    def hgetall(self, name: str) -> Awaitable[Mapping[str, str]]:
        """Return every field/value pair in one Redis hash."""

    def zcard(self, name: str) -> Awaitable[int]:
        """Return the number of members in a sorted set."""

    def zrange(self, name: str, start: int, end: int) -> Awaitable[Sequence[str]]:
        """Return sorted-set members in ascending projection order."""


@dataclass(frozen=True, slots=True)
class CachedParticipantTotals:
    """Exact totals stored adjacent to one Redis sorted-set member."""

    total_response_ms: int
    total_score: int


class RedisLeaderboardReader:
    """Read a complete Redis leaderboard page or signal that PostgreSQL should serve it."""

    def __init__(self, redis: RedisLeaderboardReadTransport) -> None:
        """Use the process-owned asynchronous Redis client."""
        self._redis = redis

    async def get_page(
        self,
        *,
        limit: int,
        offset: int,
        quiz_id: UUID,
    ) -> LeaderboardPage | None:
        """Return a validated cache page, or ``None`` for any unavailable cache state."""
        try:
            from quiz_api.services.leaderboard_reads import LeaderboardPage

            key = leaderboard_key(quiz_id)
            if await self._redis.exists(key) == 0:
                return None
            participant_ids = await self._redis.zrange(key, offset, offset + limit - 1)
            names = await self._redis.hgetall(leaderboard_names_key(quiz_id))
            totals = await self._redis.hgetall(leaderboard_totals_key(quiz_id))
            total_participants = await self._redis.zcard(key)
            entries = tuple(
                cached_standing(
                    participant_id=participant_id,
                    rank=offset + rank,
                    display_name=names[participant_id],
                    serialized_totals=totals[participant_id],
                )
                for rank, participant_id in enumerate(participant_ids, start=1)
            )
            return LeaderboardPage(
                entries=entries,
                limit=limit,
                offset=offset,
                total=total_participants,
            )
        except Exception:
            return None


def cached_standing(
    *,
    display_name: str,
    participant_id: str,
    rank: int,
    serialized_totals: str,
) -> RankedStanding:
    """Decode one exact cache record into the same contract as PostgreSQL reads."""
    totals = CachedParticipantTotals(**json.loads(serialized_totals))
    return RankedStanding(
        display_name=display_name,
        participant_id=UUID(participant_id),
        rank=rank,
        total_response_ms=totals.total_response_ms,
        total_score=totals.total_score,
    )
