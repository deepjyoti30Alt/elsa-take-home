"""Rebuild Redis leaderboard projections from PostgreSQL participant totals."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quiz_api.database.repositories import ParticipantRepository, QuizRepository
from quiz_api.services.exceptions import QuizNotFoundError
from quiz_api.services.outbox_relay import ProjectedParticipant, RedisLeaderboardProjection


class ProjectionRebuildService:
    """Replace a cache projection without treating Redis as a source of truth."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        projection: RedisLeaderboardProjection,
    ) -> None:
        """Bind the rebuild operation to durable storage and a Redis projection adapter."""
        self._projection = projection
        self._session_factory = session_factory

    async def rebuild_quiz(self, quiz_id: UUID) -> int:
        """Load authoritative totals and replace all Redis keys for one quiz."""
        async with self._session_factory() as session:
            quizzes = QuizRepository(session)
            if await quizzes.get_quiz(quiz_id) is None:
                raise QuizNotFoundError
            participants = await ParticipantRepository(session).list_all_for_projection(quiz_id)
        return await self._projection.replace_quiz(
            quiz_id=quiz_id,
            participants=(
                ProjectedParticipant(
                    display_name=participant.display_name,
                    participant_id=participant.id,
                    total_response_ms=participant.total_response_ms,
                    total_score=participant.total_score,
                )
                for participant in participants
            ),
        )
