"""Concurrency-safe tracking of quizzes that need a leaderboard broadcast."""

import asyncio
from uuid import UUID


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
