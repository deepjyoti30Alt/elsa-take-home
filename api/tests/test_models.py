"""Tests for durable quiz model constraints and metadata."""

from sqlalchemy import UniqueConstraint

from quiz_api.database.models import AnswerSubmission, OutboxEvent, Participant


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
