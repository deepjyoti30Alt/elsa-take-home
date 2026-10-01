"""Tests for coalesced leaderboard event publication."""

from uuid import UUID

from quiz_api.events import LeaderboardUpdatedEventPayload, QuizEventEnvelope
from quiz_api.services.leaderboard_ticker import LeaderboardChangeTracker, LeaderboardTicker

QUIZ_ID = UUID("10000000-0000-0000-0000-000000000001")


class FakePublisher:
    """Collect published events without connecting to Redis."""

    def __init__(self) -> None:
        """Initialize the event collection."""
        self.events: list[QuizEventEnvelope] = []

    async def publish(self, event: QuizEventEnvelope) -> None:
        """Collect one ticker event."""
        self.events.append(event)


async def fake_payload_factory(_: UUID) -> LeaderboardUpdatedEventPayload:
    """Return a minimal valid leaderboard payload for ticker behavior tests."""
    return LeaderboardUpdatedEventPayload(event_version=1, standings=(), total_participants=2)


async def test_ticker_coalesces_many_answers_into_one_latest_sequence_event() -> None:
    """A burst of answers produces one update per quiz per tick, not one per answer."""
    tracker = LeaderboardChangeTracker()
    publisher = FakePublisher()
    ticker = LeaderboardTicker(tracker, fake_payload_factory, publisher)
    await tracker.mark_changed(QUIZ_ID, 3)
    await tracker.mark_changed(QUIZ_ID, 5)
    await tracker.mark_changed(QUIZ_ID, 4)

    published_count = await ticker.tick_once()

    assert published_count == 1
    assert len(publisher.events) == 1
    assert publisher.events[0].seq == 5
    assert publisher.events[0].type == "leaderboard.updated"
