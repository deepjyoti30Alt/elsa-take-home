"""Coalesced leaderboard update publication for changed quiz projections."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quiz_api.events import (
    LeaderboardStandingEventPayload,
    LeaderboardUpdatedEventPayload,
    QuizEventEnvelope,
)
from quiz_api.observability import TICK_DURATION
from quiz_api.services.leaderboard_changes import LeaderboardChangeTracker
from quiz_api.services.leaderboard_reads import LeaderboardPage, LeaderboardReadService

logger = structlog.get_logger(__name__)


class QuizEventPublisher(Protocol):
    """Publish versioned events to the transport used by connected quiz clients."""

    async def publish(self, event: QuizEventEnvelope) -> None:
        """Publish one event to all consumers of its quiz channel."""


LeaderboardPayloadFactory = Callable[[UUID], Awaitable[LeaderboardUpdatedEventPayload]]


class LeaderboardPageReader(Protocol):
    """Read paginated durable standings for ticker payload construction."""

    async def get_page(self, *, limit: int, offset: int, quiz_id: UUID) -> LeaderboardPage:
        """Return one globally ranked quiz leaderboard page."""


class DatabaseLeaderboardPayloadFactory:
    """Build bounded leaderboard payloads from authoritative durable totals."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        compact_limit: int,
        full_limit: int,
    ) -> None:
        """Use configured limits and one database session per payload build."""
        self._compact_limit = compact_limit
        self._full_limit = full_limit
        self._session_factory = session_factory

    async def __call__(self, quiz_id: UUID) -> LeaderboardUpdatedEventPayload:
        """Return all standings below the threshold or a compact top-of-board payload."""
        async with self._session_factory() as session:
            service = LeaderboardReadService(session)
            page = await bounded_leaderboard_page(
                service,
                compact_limit=self._compact_limit,
                full_limit=self._full_limit,
                quiz_id=quiz_id,
            )
        return leaderboard_updated_payload(page)


async def bounded_leaderboard_page(
    reader: LeaderboardPageReader,
    *,
    compact_limit: int,
    full_limit: int,
    quiz_id: UUID,
) -> LeaderboardPage:
    """Return a full page up to the threshold or the compact page above it."""
    page = await reader.get_page(limit=full_limit, offset=0, quiz_id=quiz_id)
    if page.total > full_limit:
        return await reader.get_page(limit=compact_limit, offset=0, quiz_id=quiz_id)
    return page


def leaderboard_updated_payload(page: LeaderboardPage) -> LeaderboardUpdatedEventPayload:
    """Convert one bounded durable standings page into its stream event payload."""
    return LeaderboardUpdatedEventPayload(
        event_version=1,
        standings=tuple(
            LeaderboardStandingEventPayload(
                display_name=entry.display_name,
                participant_id=entry.participant_id,
                rank=entry.rank,
                total_response_ms=entry.total_response_ms,
                total_score=entry.total_score,
            )
            for entry in page.entries
        ),
        total_participants=page.total,
    )


class LeaderboardTicker:
    """Publish one leaderboard update per changed quiz for each timer interval."""

    def __init__(
        self,
        change_tracker: LeaderboardChangeTracker,
        payload_factory: LeaderboardPayloadFactory,
        publisher: QuizEventPublisher,
    ) -> None:
        """Bind the ticker to its change source, payload builder, and event publisher."""
        self._change_tracker = change_tracker
        self._payload_factory = payload_factory
        self._publisher = publisher

    async def tick_once(self) -> int:
        """Publish updates for changed quizzes and preserve failed work for retry."""
        started_at = perf_counter()
        changes = await self._change_tracker.drain()
        try:
            for quiz_id, sequence in changes.items():
                try:
                    payload = await self._payload_factory(quiz_id)
                    await self._publisher.publish(
                        QuizEventEnvelope(
                            occurred_at=datetime.now(UTC),
                            payload=payload,
                            quiz_id=quiz_id,
                            seq=sequence,
                            type="leaderboard.updated",
                        )
                    )
                except Exception:
                    logger.exception("leaderboard_ticker_quiz_failed", quiz_id=str(quiz_id))
                    await self._change_tracker.mark_changed(quiz_id, sequence)
                    # Don't re-raise - log the error and continue processing other quizzes
            return len(changes)
        finally:
            TICK_DURATION.observe(perf_counter() - started_at)

    async def run_forever(self, *, interval_seconds: float) -> None:
        """Tick indefinitely while allowing worker cancellation during application shutdown."""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.tick_once()
            except Exception:
                logger.exception("leaderboard_ticker_failed")
