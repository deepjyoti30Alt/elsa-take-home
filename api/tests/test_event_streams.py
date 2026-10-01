"""Tests for SSE stream sequencing and Redis pub/sub listener cleanup."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from starlette.requests import Request

from quiz_api.application import get_app
from quiz_api.database.models import QuizStatus
from quiz_api.events import (
    LeaderboardUpdatedEventPayload,
    QuizEventEnvelope,
    quiz_snapshot_event_payload,
)
from quiz_api.security.tokens import TokenClaims
from quiz_api.services.event_streams import QuizEventBroker
from quiz_api.services.snapshots import QuizSnapshot
from quiz_api.web.api.quizzes.router import stream_messages, stream_quiz_events
from tests.test_application import build_test_settings

QUIZ_ID = UUID("10000000-0000-0000-0000-000000000001")


class FakePubSub:
    """In-memory asynchronous pub/sub connection used to test broker lifecycle behavior."""

    def __init__(self) -> None:
        """Initialize message delivery and lifecycle recording."""
        self.closed = False
        self.messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribed: tuple[str, ...] = ()
        self.unsubscribed: tuple[str, ...] = ()

    async def aclose(self) -> None:
        """Record connection closure."""
        self.closed = True

    async def subscribe(self, *channels: str) -> None:
        """Record subscribed channels."""
        self.subscribed = channels

    async def unsubscribe(self, *channels: str) -> None:
        """Record removed channel subscriptions."""
        self.unsubscribed = channels

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        """Yield queued fake Redis messages until the broker cancels this task."""
        while True:
            yield await self.messages.get()


class FakeRedis:
    """Return a single controllable pub/sub connection."""

    def __init__(self) -> None:
        """Create the fake pub/sub connection."""
        self.connection = FakePubSub()

    def pubsub(self) -> FakePubSub:
        """Return the dedicated test pub/sub connection."""
        return self.connection


class FakeSubscription:
    """Duck-typed stream subscription for generator sequencing tests."""

    def __init__(self) -> None:
        """Create an empty event queue and cleanup marker."""
        self.closed = False
        self.queue: asyncio.Queue[QuizEventEnvelope] = asyncio.Queue()

    async def close(self) -> None:
        """Record generator cleanup."""
        self.closed = True


class FakeBroker:
    """Return a prebuilt subscription without opening a Redis connection."""

    def __init__(self, subscription: FakeSubscription) -> None:
        """Store the subscription returned to the endpoint."""
        self._subscription = subscription

    async def connect(self, _: UUID) -> FakeSubscription:
        """Return the deterministic stream subscription."""
        return self._subscription


class FakeSnapshotService:
    """Return a deterministic state snapshot without requiring PostgreSQL."""

    async def get_snapshot(self, _: UUID) -> QuizSnapshot:
        """Return the active quiz snapshot used in SSE response testing."""
        return QuizSnapshot(current_round=None, event_seq=4, id=QUIZ_ID, status=QuizStatus.ACTIVE)


def leaderboard_event(sequence: int) -> QuizEventEnvelope:
    """Build a valid event delivered by the Redis broker test."""
    return QuizEventEnvelope(
        occurred_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        payload=LeaderboardUpdatedEventPayload(event_version=1, standings=(), total_participants=1),
        quiz_id=QUIZ_ID,
        seq=sequence,
        type="leaderboard.updated",
    )


async def test_stream_messages_send_snapshot_before_newer_sequenced_events() -> None:
    """Reconnects receive current state first and ignore messages already represented by it."""
    subscription = FakeSubscription()
    snapshot = quiz_snapshot_event_payload(
        QuizSnapshot(current_round=None, event_seq=4, id=QUIZ_ID, status=QuizStatus.ACTIVE)
    )
    await subscription.queue.put(leaderboard_event(4))
    await subscription.queue.put(leaderboard_event(5))
    messages = stream_messages(subscription, snapshot)  # type: ignore[arg-type]

    first = await anext(messages)
    second = await anext(messages)
    await messages.aclose()

    assert b"event: quiz.snapshot" in first.encode()
    assert b"id: 4" in first.encode()
    assert b"event: leaderboard.updated" in second.encode()
    assert b"id: 5" in second.encode()
    assert subscription.closed


async def test_broker_starts_and_stops_one_redis_listener_for_a_quiz() -> None:
    """A quiz channel is subscribed only while this process has a local stream listener."""
    redis = FakeRedis()
    broker = QuizEventBroker(redis, queue_size=10)  # type: ignore[arg-type]
    subscription = await broker.connect(QUIZ_ID)
    await asyncio.sleep(0)

    await redis.connection.messages.put(
        {"type": "message", "data": leaderboard_event(5).model_dump_json()}
    )
    received = await asyncio.wait_for(subscription.queue.get(), timeout=0.1)
    await subscription.close()

    assert received.seq == 5
    assert redis.connection.subscribed == (f"quiz:{QUIZ_ID}:events",)
    assert redis.connection.unsubscribed == (f"quiz:{QUIZ_ID}:events",)
    assert redis.connection.closed


async def test_broker_shutdown_wakes_an_active_stream_for_clean_generator_exit() -> None:
    """Application shutdown unblocks a waiting SSE generator before Redis is closed."""
    broker = QuizEventBroker(FakeRedis(), queue_size=10)  # type: ignore[arg-type]
    subscription = await broker.connect(QUIZ_ID)
    await broker.close()

    assert await subscription.queue.get() is None


async def test_event_endpoint_configures_heartbeats_and_sends_snapshot_first() -> None:
    """The native EventSource response has a bounded heartbeat and initial state event."""
    app = get_app(build_test_settings())
    subscription = FakeSubscription()
    response = await stream_quiz_events(
        QUIZ_ID,
        stream_request(app),
        TokenClaims(participant_id=QUIZ_ID, purpose="stream", quiz_id=QUIZ_ID),
        FakeBroker(subscription),  # type: ignore[arg-type]
        FakeSnapshotService(),  # type: ignore[arg-type]
    )
    messages = response.body_iterator
    first = await anext(messages)
    await messages.aclose()

    assert response._ping_interval == 15
    assert b"event: quiz.snapshot" in first.encode()
    assert subscription.closed


def stream_request(app: FastAPI) -> Request:
    """Build the minimal request scope needed by the direct SSE endpoint test."""
    return Request(
        {
            "app": app,
            "headers": [],
            "method": "GET",
            "path": f"/v1/quizzes/{QUIZ_ID}/events",
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "type": "http",
        }
    )
