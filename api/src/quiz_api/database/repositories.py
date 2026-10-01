"""Typed SQLAlchemy repositories for durable quiz runtime state."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import UnaryExpression

from quiz_api.database.models import (
    AnswerSubmission,
    OutboxEvent,
    Participant,
    Question,
    Quiz,
    Round,
)


def leaderboard_ordering() -> tuple[
    UnaryExpression[Any], UnaryExpression[int], UnaryExpression[UUID]
]:
    """Return the canonical ordering shared by SQL and Redis projections."""
    return (
        cast(UnaryExpression[Any], desc(Participant.total_score)),
        Participant.total_response_ms.asc(),
        Participant.id.asc(),
    )


class QuizRepository:
    """Load and persist quiz, round, and immutable question state."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind this repository to a caller-owned database session."""
        self._session = session

    async def get_quiz(self, quiz_id: UUID) -> Quiz | None:
        """Return a quiz by ID without acquiring a row lock."""
        result = await self._session.execute(select(Quiz).where(Quiz.id == quiz_id))
        return result.scalar_one_or_none()

    async def get_round_for_share(self, quiz_id: UUID, round_id: UUID) -> Round | None:
        """Lock a round in shared mode for an answer transaction."""
        statement = (
            select(Round)
            .where(Round.id == round_id, Round.quiz_id == quiz_id)
            .with_for_update(read=True)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_round_for_update(self, quiz_id: UUID, round_id: UUID) -> Round | None:
        """Lock a round exclusively for a host state transition."""
        statement = (
            select(Round).where(Round.id == round_id, Round.quiz_id == quiz_id).with_for_update()
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_question(self, question_id: UUID) -> Question | None:
        """Return the immutable question associated with a round."""
        result = await self._session.execute(select(Question).where(Question.id == question_id))
        return result.scalar_one_or_none()

    def add_question(self, question: Question) -> None:
        """Stage a question; the caller's transaction controls persistence."""
        self._session.add(question)

    def add_quiz(self, quiz: Quiz) -> None:
        """Stage a quiz; the caller's transaction controls persistence."""
        self._session.add(quiz)

    def add_round(self, round_: Round) -> None:
        """Stage a round; the caller's transaction controls persistence."""
        self._session.add(round_)


class ParticipantRepository:
    """Load participant identities and deterministic leaderboard pages."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind this repository to a caller-owned database session."""
        self._session = session

    async def get_participant(self, quiz_id: UUID, participant_id: UUID) -> Participant | None:
        """Return a participant only when it belongs to the supplied quiz."""
        statement = select(Participant).where(
            Participant.id == participant_id,
            Participant.quiz_id == quiz_id,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_join_key(self, quiz_id: UUID, join_key: str) -> Participant | None:
        """Return the participant created by an idempotent join attempt."""
        statement = select(Participant).where(
            Participant.quiz_id == quiz_id,
            Participant.join_key == join_key,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_leaderboard(
        self,
        quiz_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> Sequence[Participant]:
        """Return one deterministically ordered page of quiz participants."""
        statement: Select[Participant] = (
            select(Participant)
            .where(Participant.quiz_id == quiz_id)
            .order_by(*leaderboard_ordering())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()

    def add_participant(self, participant: Participant) -> None:
        """Stage a participant; the caller's transaction controls persistence."""
        self._session.add(participant)


class AnswerRepository:
    """Load and stage the single allowed answer for each participant-round pair."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind this repository to a caller-owned database session."""
        self._session = session

    async def get_submission(
        self,
        participant_id: UUID,
        round_id: UUID,
    ) -> AnswerSubmission | None:
        """Return an existing answer to support idempotent retry decisions."""
        statement = select(AnswerSubmission).where(
            AnswerSubmission.participant_id == participant_id,
            AnswerSubmission.round_id == round_id,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    def add_submission(self, submission: AnswerSubmission) -> None:
        """Stage an answer; the caller's transaction controls persistence."""
        self._session.add(submission)


class OutboxRepository:
    """Read and update durable events used to build cache projections."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind this repository to a caller-owned database session."""
        self._session = session

    async def list_unpublished_for_delivery(self, *, limit: int) -> Sequence[OutboxEvent]:
        """Lease a batch of unpublished events without blocking another relay."""
        statement = (
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(statement)
        return result.scalars().all()

    def add_event(self, event: OutboxEvent) -> None:
        """Stage an outbox event; the caller's transaction controls persistence."""
        self._session.add(event)

    def mark_published(self, event: OutboxEvent, published_at: datetime) -> None:
        """Record successful event delivery after projection work completes."""
        event.published_at = published_at
