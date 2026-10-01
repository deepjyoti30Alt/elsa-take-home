"""Tests for pure answer-transaction validation and event payloads."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from quiz_api.database.models import RoundStatus
from quiz_api.services.answers import (
    answer_accepted_payload,
    ensure_round_is_open,
    is_same_answer_retry,
)
from quiz_api.services.exceptions import RoundNotOpenError
from quiz_api.services.scoring import ScoreResult

OPENS_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
CLOSES_AT = OPENS_AT + timedelta(seconds=10)


def test_answer_payload_contains_projection_totals() -> None:
    """The outbox payload contains absolute values safe for retrying projections."""
    payload = answer_accepted_payload(
        participant_id=UUID("10000000-0000-0000-0000-000000000001"),
        score=ScoreResult(awarded_points=175, is_correct=True, response_ms=2500),
        total_response_ms=2500,
        total_score=175,
    )

    assert payload == {
        "event_version": 1,
        "is_correct": True,
        "participant_id": "10000000-0000-0000-0000-000000000001",
        "response_ms": 2500,
        "total_response_ms": 2500,
        "total_score": 175,
    }


def test_same_answer_retries_are_normalized_but_changed_answers_are_not() -> None:
    """Idempotent retries preserve the original answer instead of rescoring it."""
    assert is_same_answer_retry(" Alleviate ", "alleviate")
    assert not is_same_answer_retry("alleviate", "revoke")


@pytest.mark.parametrize(
    ("status", "submitted_at"),
    [
        (RoundStatus.PENDING, OPENS_AT),
        (RoundStatus.CLOSED, OPENS_AT + timedelta(seconds=1)),
        (RoundStatus.OPEN, CLOSES_AT),
    ],
)
def test_answers_outside_the_open_database_time_window_are_rejected(
    status: RoundStatus,
    submitted_at: datetime,
) -> None:
    """Only an open round strictly before its close time may accept an answer."""
    with pytest.raises(RoundNotOpenError):
        ensure_round_is_open(status, OPENS_AT, CLOSES_AT, submitted_at)
