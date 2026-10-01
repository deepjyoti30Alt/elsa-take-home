"""Tests for durable quiz model constraints and metadata."""

from sqlalchemy import UniqueConstraint

from quiz_api.database.models import (
    AnswerSubmission,
    OutboxEvent,
    OutboxEventType,
    Participant,
    Quiz,
    QuizStatus,
    Round,
    RoundStatus,
    ScoreLedgerEntry,
    ScoreReason,
)


def constraint_names(model: type[AnswerSubmission | OutboxEvent | Participant]) -> set[str]:
    """Return the explicitly named unique constraints for one ORM model."""
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name is not None
    }


def test_models_define_idempotency_and_event_ordering_constraints() -> None:
    """The metadata protects joins, answers, and outbox event ordering."""
    assert "uq_participant_quiz_join_key" in constraint_names(Participant)
    assert "uq_answer_participant_round" in constraint_names(AnswerSubmission)
    assert "uq_outbox_quiz_sequence" in constraint_names(OutboxEvent)


def test_models_persist_enum_values_matching_migration_constraints() -> None:
    """SQLAlchemy must bind lowercase enum values rather than uppercase member names."""
    assert Quiz.__table__.c.status.type.enums == [member.value for member in QuizStatus]
    assert Round.__table__.c.status.type.enums == [member.value for member in RoundStatus]
    assert ScoreLedgerEntry.__table__.c.reason.type.enums == [
        member.value for member in ScoreReason
    ]
    assert OutboxEvent.__table__.c.type.type.enums == [member.value for member in OutboxEventType]
