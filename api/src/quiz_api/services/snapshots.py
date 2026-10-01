"""Read models that safely project current quiz state to clients."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.database.models import QuizStatus, RoundStatus
from quiz_api.database.repositories import QuizRepository
from quiz_api.services.exceptions import QuizNotFoundError


@dataclass(frozen=True, slots=True)
class QuestionSnapshot:
    """Client-safe question presentation that excludes the answer key."""

    options: tuple[str, ...]
    prompt: str


@dataclass(frozen=True, slots=True)
class RoundSnapshot:
    """Client-safe state for the quiz's shared current round."""

    closes_at: datetime | None
    id: UUID
    opens_at: datetime | None
    question: QuestionSnapshot
    status: RoundStatus


@dataclass(frozen=True, slots=True)
class QuizSnapshot:
    """Current quiz lifecycle state and optional active round presentation."""

    current_round: RoundSnapshot | None
    id: UUID
    status: QuizStatus
    event_seq: int = 0


class QuizSnapshotService:
    """Load client-visible quiz state without loading answer keys into responses."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the read service to one caller-owned database session."""
        self._quizzes = QuizRepository(session)

    async def get_snapshot(self, quiz_id: UUID) -> QuizSnapshot:
        """Return the public state of a quiz and its current round, if any."""
        quiz = await self._quizzes.get_quiz(quiz_id)
        if quiz is None:
            raise QuizNotFoundError
        if quiz.current_round_id is None:
            return QuizSnapshot(
                current_round=None,
                event_seq=quiz.next_event_seq,
                id=quiz.id,
                status=quiz.status,
            )

        round_ = await self._quizzes.get_round(quiz.id, quiz.current_round_id)
        if round_ is None:
            message = "Quiz references a round that does not exist."
            raise RuntimeError(message)
        question = await self._quizzes.get_question(round_.question_id)
        if question is None:
            message = "Round references a question that does not exist."
            raise RuntimeError(message)
        return QuizSnapshot(
            current_round=RoundSnapshot(
                closes_at=round_.closes_at,
                id=round_.id,
                opens_at=round_.opens_at,
                question=QuestionSnapshot(options=tuple(question.options), prompt=question.prompt),
                status=round_.status,
            ),
            id=quiz.id,
            status=quiz.status,
            event_seq=quiz.next_event_seq,
        )
