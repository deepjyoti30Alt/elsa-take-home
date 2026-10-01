"""Host-authorized reset of one quiz's disposable demo runtime state."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.database.models import OutboxEvent, Participant, QuizStatus, Round, RoundStatus
from quiz_api.database.repositories import ParticipantRepository, QuizRepository
from quiz_api.services.exceptions import QuizNotFoundError
from quiz_api.services.outbox_relay import RedisLeaderboardProjection


@dataclass(frozen=True, slots=True)
class QuizResetResult:
    """Counts returned after resetting a quiz to its pre-game state."""

    removed_participants: int


class QuizResetService:
    """Clear mutable quiz data while preserving authored questions and rounds."""

    def __init__(self, session: AsyncSession, projection: RedisLeaderboardProjection) -> None:
        """Use a request-owned database session and shared Redis projection transport."""
        self._participants = ParticipantRepository(session)
        self._projection = projection
        self._quizzes = QuizRepository(session)
        self._session = session

    async def reset_quiz(self, quiz_id: UUID) -> QuizResetResult:
        """Restore rounds and standings so the host can rerun a complete demo quiz."""
        async with self._session.begin():
            quiz = await self._quizzes.get_quiz_for_update(quiz_id)
            if quiz is None:
                raise QuizNotFoundError
            removed_participants = await self._participants.count_participants(quiz_id)
            await self._session.execute(delete(OutboxEvent).where(OutboxEvent.quiz_id == quiz_id))
            await self._session.execute(delete(Participant).where(Participant.quiz_id == quiz_id))
            await self._session.execute(
                update(Round)
                .where(Round.quiz_id == quiz_id)
                .values(closes_at=None, opens_at=None, status=RoundStatus.PENDING)
            )
            quiz.current_round_id = None
            quiz.status = QuizStatus.DRAFT

        await self._projection.replace_quiz(quiz_id=quiz_id, participants=())
        return QuizResetResult(removed_participants=removed_participants)
