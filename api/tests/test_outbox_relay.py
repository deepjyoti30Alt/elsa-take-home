"""Tests for durable outbox delivery to Redis projection adapters."""

from datetime import UTC, datetime
from uuid import UUID

from quiz_api.database.models import OutboxEvent, OutboxEventType
from quiz_api.events import AnswerAcceptedEventPayload, outbox_event_to_envelope
from quiz_api.services.outbox_relay import (
    RedisLeaderboardProjection,
    RedisQuizEventPublisher,
    leaderboard_key,
    leaderboard_names_key,
    leaderboard_sort_score,
)

QUIZ_ID = UUID("10000000-0000-0000-0000-000000000001")
PARTICIPANT_ID = UUID("20000000-0000-0000-0000-000000000002")


class FakeRedis:
    """Record Redis commands without requiring a running Redis service."""

    def __init__(self) -> None:
        """Initialize the command recording collections."""
        self.hashes: list[tuple[str, dict[str, str]]] = []
        self.published: list[tuple[str, str]] = []
        self.sorted_sets: list[tuple[str, dict[str, float]]] = []

    async def hset(self, name: str, **kwargs: object) -> int:
        """Record a hash mapping write."""
        mapping = kwargs["mapping"]
        assert isinstance(mapping, dict)
        self.hashes.append((name, mapping))
        return 1

    async def publish(self, channel: str, message: str) -> int:
        """Record a pub/sub message."""
        self.published.append((channel, message))
        return 1

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        """Record an absolute sorted-set write."""
        self.sorted_sets.append((name, mapping))
        return 1


def answer_event() -> OutboxEvent:
    """Build a durable answer event that includes authoritative totals."""
    return OutboxEvent(
        created_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        payload={
            "display_name": "Ada",
            "event_version": 1,
            "is_correct": True,
            "participant_id": str(PARTICIPANT_ID),
            "response_ms": 300,
            "total_response_ms": 300,
            "total_score": 195,
        },
        quiz_id=QUIZ_ID,
        seq=1,
        type=OutboxEventType.ANSWER_ACCEPTED,
    )


async def test_projection_writes_absolute_totals_and_name_for_answer_events() -> None:
    """Repeated relay attempts overwrite the same participant rather than double counting."""
    redis = FakeRedis()
    projection = RedisLeaderboardProjection(redis)
    envelope = outbox_event_to_envelope(answer_event())
    assert isinstance(envelope.payload, AnswerAcceptedEventPayload)

    await projection.apply_answer(quiz_id=QUIZ_ID, payload=envelope.payload)

    assert redis.sorted_sets == [
        (
            leaderboard_key(QUIZ_ID),
            {str(PARTICIPANT_ID): leaderboard_sort_score(195, 300)},
        )
    ]
    assert redis.hashes == [(leaderboard_names_key(QUIZ_ID), {str(PARTICIPANT_ID): "Ada"})]


async def test_publisher_serializes_the_versioned_envelope_to_the_quiz_channel() -> None:
    """Round events are emitted only by a worker, never from the command handler."""
    redis = FakeRedis()
    publisher = RedisQuizEventPublisher(redis)

    await publisher.publish(outbox_event_to_envelope(answer_event()))

    assert redis.published[0][0] == f"quiz:{QUIZ_ID}:events"
    assert '"type":"answer.accepted"' in redis.published[0][1]
