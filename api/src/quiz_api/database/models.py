"""Typed SQLAlchemy models for durable quiz runtime state."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from quiz_api.database.base import Base


class QuizStatus(StrEnum):
    """Lifecycle states for a host-paced quiz."""

    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"


class RoundStatus(StrEnum):
    """Lifecycle states for an individual quiz round."""

    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"


class ScoreReason(StrEnum):
    """Reasons a score-ledger entry was created."""

    CORRECT_ANSWER = "correct_answer"


class OutboxEventType(StrEnum):
    """Durable event types emitted by quiz state changes."""

    ANSWER_ACCEPTED = "answer_accepted"
    ROUND_CLOSED = "round_closed"
    ROUND_OPENED = "round_opened"


class Question(Base):
    """Immutable vocabulary question and its server-only answer key."""

    __tablename__ = "question"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSONB)
    correct_answer: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Quiz(Base):
    """A host-paced quiz session and its participant collection."""

    __tablename__ = "quiz"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[QuizStatus] = mapped_column(
        Enum(QuizStatus, name="quiz_status", native_enum=False),
        nullable=False,
        default=QuizStatus.DRAFT,
    )
    host_id: Mapped[str] = mapped_column(String(255), nullable=False)
    current_round_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("round.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    current_round: Mapped[Round | None] = relationship(
        foreign_keys=[current_round_id],
        post_update=True,
    )
    participants: Mapped[list[Participant]] = relationship(back_populates="quiz")
    rounds: Mapped[list[Round]] = relationship(
        back_populates="quiz",
        foreign_keys="Round.quiz_id",
    )


class Round(Base):
    """A timed question presented simultaneously to a quiz's participants."""

    __tablename__ = "round"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    quiz_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("quiz.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("question.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[RoundStatus] = mapped_column(
        Enum(RoundStatus, name="round_status", native_enum=False),
        nullable=False,
        default=RoundStatus.PENDING,
    )
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    quiz: Mapped[Quiz] = relationship(back_populates="rounds", foreign_keys=[quiz_id])
    question: Mapped[Question] = relationship()


class Participant(Base):
    """A guest participant and the running totals used for rankings."""

    __tablename__ = "participant"
    __table_args__ = (
        UniqueConstraint("quiz_id", "join_key", name="uq_participant_quiz_join_key"),
        Index("ix_participant_quiz_ranking", "quiz_id", "total_score", "total_response_ms"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    quiz_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("quiz.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    join_key: Mapped[str] = mapped_column(String(255), nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_response_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    quiz: Mapped[Quiz] = relationship(back_populates="participants")


class AnswerSubmission(Base):
    """The one durable answer a participant may submit for a round."""

    __tablename__ = "answer_submission"
    __table_args__ = (
        UniqueConstraint("participant_id", "round_id", name="uq_answer_participant_round"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    participant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("participant.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("round.id", ondelete="CASCADE"),
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    )
    answer: Mapped[str] = mapped_column(String(255), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    awarded_points: Mapped[int] = mapped_column(Integer, nullable=False)


class ScoreLedgerEntry(Base):
    """An auditable immutable record of a participant score change."""

    __tablename__ = "score_ledger"
    __table_args__ = (
        UniqueConstraint("participant_id", "round_id", name="uq_score_ledger_participant_round"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    participant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("participant.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("round.id", ondelete="CASCADE"),
        nullable=False,
    )
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[ScoreReason] = mapped_column(
        Enum(ScoreReason, name="score_reason", native_enum=False),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class OutboxEvent(Base):
    """A durable event awaiting safe projection and real-time publication."""

    __tablename__ = "outbox_event"
    __table_args__ = (
        UniqueConstraint("quiz_id", "seq", name="uq_outbox_quiz_sequence"),
        Index("ix_outbox_unpublished", "published_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    quiz_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("quiz.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type: Mapped[OutboxEventType] = mapped_column(
        Enum(OutboxEventType, name="outbox_event_type", native_enum=False),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
