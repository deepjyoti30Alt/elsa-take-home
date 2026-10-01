"""Durable outbox relay for Redis leaderboard projection and quiz events."""

import asyncio
import json
from collections.abc import Awaitable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quiz_api.database.models import OutboxEventType
from quiz_api.database.repositories import OutboxRepository
from quiz_api.events import (
    AnswerAcceptedEventPayload,
    QuizEventEnvelope,
    outbox_event_to_envelope,
    quiz_channel,
)
from quiz_api.services.leaderboard_changes import LeaderboardChangeTracker

LEADERBOARD_SCORE_SCALE = 1_000_000_000


@dataclass(frozen=True, slots=True)
class ProjectedParticipant:
    """Durable participant totals required to rebuild one leaderboard cache key."""

    display_name: str
    participant_id: UUID
    total_response_ms: int
    total_score: int


class RedisEventTransport(Protocol):
    """Subset of Redis commands required by the projection and publisher."""

    def hset(
        self,
        name: str,
        key: str | None = None,
        value: str | None = None,
        mapping: Mapping[str, str] | None = None,
    ) -> Awaitable[int]:
        """Set one or more values in a Redis hash."""

    def delete(self, *names: str) -> Awaitable[int]:
        """Delete one or more Redis keys."""

    def publish(self, channel: str, message: str) -> Awaitable[int]:
        """Publish a serialized event to a Redis pub/sub channel."""

    def zadd(self, name: str, mapping: Mapping[str, float]) -> Awaitable[int]:
        """Add or update sorted-set members with absolute scores."""


class RedisLeaderboardProjection:
    """Maintain Redis leaderboard keys using idempotent absolute participant totals."""

    def __init__(self, redis: RedisEventTransport) -> None:
        """Use the process-owned asynchronous Redis client."""
        self._redis = redis

    async def apply_answer(self, *, quiz_id: UUID, payload: AnswerAcceptedEventPayload) -> None:
        """Upsert one participant's totals and display name without incrementing Redis."""
        participant_id = str(payload.participant_id)
        await self._redis.zadd(
            leaderboard_key(quiz_id),
            {
                participant_id: leaderboard_sort_score(
                    payload.total_score,
                    payload.total_response_ms,
                )
            },
        )
        await self._redis.hset(
            leaderboard_names_key(quiz_id),
            mapping={participant_id: payload.display_name},
        )
        await self._redis.hset(
            leaderboard_totals_key(quiz_id),
            mapping={
                participant_id: serialize_totals(
                    total_response_ms=payload.total_response_ms,
                    total_score=payload.total_score,
                )
            },
        )

    async def replace_quiz(
        self,
        *,
        quiz_id: UUID,
        participants: Iterable[ProjectedParticipant],
    ) -> int:
        """Replace a quiz projection from durable totals after cache loss or repair."""
        score_mapping: dict[str, float] = {}
        name_mapping: dict[str, str] = {}
        totals_mapping: dict[str, str] = {}
        for participant in participants:
            participant_id = str(participant.participant_id)
            name_mapping[participant_id] = participant.display_name
            totals_mapping[participant_id] = serialize_totals(
                total_response_ms=participant.total_response_ms,
                total_score=participant.total_score,
            )
            score_mapping[participant_id] = leaderboard_sort_score(
                participant.total_score,
                participant.total_response_ms,
            )
        await self._redis.delete(
            leaderboard_key(quiz_id),
            leaderboard_names_key(quiz_id),
            leaderboard_totals_key(quiz_id),
        )
        if score_mapping:
            await self._redis.zadd(leaderboard_key(quiz_id), score_mapping)
            await self._redis.hset(leaderboard_names_key(quiz_id), mapping=name_mapping)
            await self._redis.hset(leaderboard_totals_key(quiz_id), mapping=totals_mapping)
        return len(score_mapping)


class RedisQuizEventPublisher:
    """Serialize validated quiz events to their dedicated Redis pub/sub channel."""

    def __init__(self, redis: RedisEventTransport) -> None:
        """Use the process-owned asynchronous Redis client."""
        self._redis = redis

    async def publish(self, event: QuizEventEnvelope) -> None:
        """Publish one versioned event for all local stream handlers of a quiz."""
        await self._redis.publish(quiz_channel(event.quiz_id), event.model_dump_json())


class OutboxRelay:
    """Project committed outbox events, leaving failures unpublished for safe retry."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        change_tracker: LeaderboardChangeTracker,
        projection: RedisLeaderboardProjection,
        publisher: RedisQuizEventPublisher,
    ) -> None:
        """Bind the relay to one database-session factory and Redis delivery adapters."""
        self._change_tracker = change_tracker
        self._projection = projection
        self._publisher = publisher
        self._session_factory = session_factory

    async def relay_once(self, *, batch_size: int) -> int:
        """Deliver one locked batch and return the number marked published."""
        async with self._session_factory.begin() as session:
            repository = OutboxRepository(session)
            events = await repository.list_unpublished_for_delivery(limit=batch_size)
            for event in events:
                envelope = outbox_event_to_envelope(event)
                await self._deliver(event.type, envelope)
                repository.mark_published(event, datetime.now(UTC))
            return len(events)

    async def run_forever(
        self,
        *,
        batch_size: int,
        poll_interval_seconds: float,
        retry_max_seconds: float,
    ) -> None:
        """Continuously relay committed events with bounded backoff after any failure."""
        failures = 0
        while True:
            try:
                delivered = await self.relay_once(batch_size=batch_size)
                failures = 0
                if delivered == 0:
                    await asyncio.sleep(poll_interval_seconds)
            except Exception:
                failures += 1
                await asyncio.sleep(retry_delay_seconds(failures, retry_max_seconds))

    async def _deliver(self, event_type: OutboxEventType, event: QuizEventEnvelope) -> None:
        """Apply a projection or publish a state transition according to event type."""
        if event_type is OutboxEventType.ANSWER_ACCEPTED:
            payload = cast(AnswerAcceptedEventPayload, event.payload)
            await self._projection.apply_answer(quiz_id=event.quiz_id, payload=payload)
            await self._change_tracker.mark_changed(event.quiz_id, event.seq)
            return
        await self._publisher.publish(event)


def leaderboard_key(quiz_id: UUID) -> str:
    """Return the sorted-set key holding one quiz's projected standings."""
    return f"quiz:{quiz_id}:leaderboard"


def leaderboard_names_key(quiz_id: UUID) -> str:
    """Return the hash key storing participant display names for a quiz projection."""
    return f"quiz:{quiz_id}:leaderboard:names"


def leaderboard_totals_key(quiz_id: UUID) -> str:
    """Return the hash key storing exact score totals for Redis leaderboard reads."""
    return f"quiz:{quiz_id}:leaderboard:totals"


def leaderboard_sort_score(total_score: int, total_response_ms: int) -> float:
    """Encode score-descending and response-time-ascending order for Redis ZRANGE."""
    return float((-total_score * LEADERBOARD_SCORE_SCALE) + total_response_ms)


def retry_delay_seconds(failures: int, maximum_seconds: float) -> float:
    """Return bounded exponential retry delay for consecutive relay failures."""
    return min(float(2 ** max(failures - 1, 0)), maximum_seconds)


def serialize_totals(*, total_response_ms: int, total_score: int) -> str:
    """Serialize exact durable totals kept alongside the sorted-set ordering score."""
    return json.dumps(
        {"total_response_ms": total_response_ms, "total_score": total_score},
        separators=(",", ":"),
    )
