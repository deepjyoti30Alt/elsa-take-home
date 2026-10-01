"""Tests for coalesced leaderboard event publication."""

import asyncio
from uuid import UUID

import pytest

from quiz_api.events import LeaderboardUpdatedEventPayload, QuizEventEnvelope
from quiz_api.services.leaderboard import RankedStanding
from quiz_api.services.leaderboard_reads import LeaderboardPage
from quiz_api.services.leaderboard_ticker import (
    LeaderboardChangeTracker,
    LeaderboardTicker,
    bounded_leaderboard_page,
    leaderboard_updated_payload,
)

QUIZ_ID = UUID("10000000-0000-0000-0000-000000000001")


class FakePublisher:
    """Collect published events without connecting to Redis."""

    def __init__(self) -> None:
        """Initialize the event collection."""
        self.events: list[QuizEventEnvelope] = []

    async def publish(self, event: QuizEventEnvelope) -> None:
        """Collect one ticker event."""
        self.events.append(event)


class FailingPublisher(FakePublisher):
    """Fail a configured number of deliveries before accepting events."""

    def __init__(self, *, failures: int) -> None:
        """Initialize the remaining failure count."""
        super().__init__()
        self._failures = failures

    async def publish(self, event: QuizEventEnvelope) -> None:
        """Fail before delivery until the configured transient outage clears."""
        if self._failures > 0:
            self._failures -= 1
            message = "Redis is unavailable"
            raise ConnectionError(message)
        await super().publish(event)


class FakePageReader:
    """Return configured pages and record requested limits for payload-boundary tests."""

    def __init__(self, pages: list[LeaderboardPage]) -> None:
        """Store pages in the order the ticker should request them."""
        self.calls: list[int] = []
        self.pages = pages

    async def get_page(self, *, limit: int, offset: int, quiz_id: UUID) -> LeaderboardPage:
        """Record the request and return the next configured durable page."""
        assert offset == 0
        assert quiz_id == QUIZ_ID
        self.calls.append(limit)
        return self.pages.pop(0)


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


async def test_ticker_payload_keeps_full_standings_at_the_configured_threshold() -> None:
    """Quizzes at the full limit keep their entire standings in the stream payload."""
    page = leaderboard_page(total=500)
    reader = FakePageReader([page])

    selected_page = await bounded_leaderboard_page(
        reader,
        compact_limit=50,
        full_limit=500,
        quiz_id=QUIZ_ID,
    )

    assert reader.calls == [500]
    assert leaderboard_updated_payload(selected_page).total_participants == 500


async def test_ticker_payload_uses_compact_page_above_the_configured_threshold() -> None:
    """Large quizzes send top standings while REST remains available for pagination."""
    reader = FakePageReader([leaderboard_page(total=501), leaderboard_page(total=501)])

    selected_page = await bounded_leaderboard_page(
        reader,
        compact_limit=50,
        full_limit=500,
        quiz_id=QUIZ_ID,
    )

    assert reader.calls == [500, 50]
    assert leaderboard_updated_payload(selected_page).total_participants == 501


async def test_concurrent_change_marks_keep_the_highest_durable_sequence() -> None:
    """Concurrent answer relays cannot regress the sequence used for one quiz update."""
    tracker = LeaderboardChangeTracker()

    await asyncio.gather(*(tracker.mark_changed(QUIZ_ID, sequence) for sequence in range(1, 101)))

    assert await tracker.drain() == {QUIZ_ID: 100}


async def test_failed_ticker_delivery_is_requeued_for_recovery() -> None:
    """A transient publish failure preserves the changed quiz for the next ticker run."""
    tracker = LeaderboardChangeTracker()
    publisher = FailingPublisher(failures=1)
    ticker = LeaderboardTicker(tracker, fake_payload_factory, publisher)
    await tracker.mark_changed(QUIZ_ID, 9)

    with pytest.raises(ConnectionError):
        await ticker.tick_once()

    assert await ticker.tick_once() == 1
    assert publisher.events[0].seq == 9


def leaderboard_page(*, total: int) -> LeaderboardPage:
    """Build a small deterministic page whose total models the threshold boundary."""
    return LeaderboardPage(
        entries=(
            RankedStanding(
                display_name="Ada",
                participant_id=QUIZ_ID,
                rank=1,
                total_response_ms=300,
                total_score=195,
            ),
        ),
        limit=500,
        offset=0,
        total=total,
    )
