"""Coalesced leaderboard update publication for changed quiz projections."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quiz_api.events import (
    LeaderboardStandingEventPayload,
    LeaderboardUpdatedEventPayload,
    QuizEventEnvelope,
)
from quiz_api.services.leaderboard_reads import LeaderboardReadService

logger = structlog.get_logger(__name__)


class QuizEventPublisher(Protocol):
    """Publish versioned events to the transport used by connected quiz clients."""

    async def publish(self, event: QuizEventEnvelope) -> None:
        """Publish one event to all consumers of its quiz channel."""


LeaderboardPayloadFactory = Callable[[UUID], Awaitable[LeaderboardUpdatedEventPayload]]


class LeaderboardChangeTracker:
    """Track only the newest score-changing durable event for each quiz."""

    def __init__(self) -> None:
        """Create an empty, concurrency-safe change collection."""
        self._changes: dict[UUID, int] = {}
        self._lock = asyncio.Lock()

    async def mark_changed(self, quiz_id: UUID, sequence: int) -> None:
        """Remember the greatest accepted-answer sequence for one changed quiz."""
        async with self._lock:
            self._changes[quiz_id] = max(sequence, self._changes.get(quiz_id, 0))

    async def drain(self) -> dict[UUID, int]:
        """Return and clear the current coalesced change set."""
        async with self._lock:
            changes = self._changes
            self._changes = {}
            return changes


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
            page = await service.get_page(limit=self._full_limit, offset=0, quiz_id=quiz_id)
            if page.total > self._full_limit:
                page = await service.get_page(
                    limit=self._compact_limit,
                    offset=0,
                    quiz_id=quiz_id,
                )
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
        changes = await self._change_tracker.drain()
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
                await self._change_tracker.mark_changed(quiz_id, sequence)
                raise
        return len(changes)

    async def run_forever(self, *, interval_seconds: float) -> None:
        """Tick indefinitely while allowing worker cancellation during application shutdown."""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.tick_once()
            except Exception:
                logger.exception("leaderboard_ticker_failed")
