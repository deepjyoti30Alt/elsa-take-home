"""Paginated, deterministic leaderboard read models."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.database.repositories import ParticipantRepository, QuizRepository
from quiz_api.services.exceptions import QuizNotFoundError
from quiz_api.services.leaderboard import RankedStanding
from quiz_api.services.leaderboard_cache import RedisLeaderboardReader


@dataclass(frozen=True, slots=True)
class LeaderboardPage:
    """One page of globally ranked quiz participants."""

    entries: tuple[RankedStanding, ...]
    limit: int
    offset: int
    total: int


class LeaderboardReadService:
    """Read a deterministic leaderboard page from the durable source of truth."""

    def __init__(self, session: AsyncSession, cache: RedisLeaderboardReader | None = None) -> None:
        """Bind the read service to one caller-owned database session."""
        self._participants = ParticipantRepository(session)
        self._quizzes = QuizRepository(session)
        self._cache = cache

    async def get_page(self, *, limit: int, offset: int, quiz_id: UUID) -> LeaderboardPage:
        """Return a page with ranks based on the full ordered participant collection."""
        if await self._quizzes.get_quiz(quiz_id) is None:
            raise QuizNotFoundError
        if self._cache is not None:
            cached_page = await self._cache.get_page(limit=limit, offset=offset, quiz_id=quiz_id)
            if cached_page is not None:
                return cached_page
        participants = await self._participants.list_leaderboard(
            quiz_id,
            limit=limit,
            offset=offset,
        )
        total = await self._participants.count_participants(quiz_id)
        entries = tuple(
            RankedStanding(
                display_name=participant.display_name,
                participant_id=participant.id,
                rank=offset + index,
                total_response_ms=participant.total_response_ms,
                total_score=participant.total_score,
            )
            for index, participant in enumerate(participants, start=1)
        )
        return LeaderboardPage(entries=entries, limit=limit, offset=offset, total=total)
