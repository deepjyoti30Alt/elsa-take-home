"""Tests for pure real-time answer scoring."""

from datetime import UTC, datetime, timedelta

import pytest

from quiz_api.services.scoring import ScoringWindowError, calculate_score

OPENS_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
CLOSES_AT = OPENS_AT + timedelta(seconds=10)


@pytest.mark.parametrize(
    ("submitted_at", "submitted_answer", "expected_points", "expected_response_ms"),
    [
        (OPENS_AT, "alleviate", 200, 0),
        (OPENS_AT + timedelta(seconds=5), " ALLEVIATE ", 150, 5000),
        (CLOSES_AT, "alleviate", 100, 10_000),
        (OPENS_AT + timedelta(seconds=1), "revoke", 0, 1000),
    ],
)
def test_calculate_score_applies_correctness_and_linear_speed_bonus(
    submitted_at: datetime,
    submitted_answer: str,
    expected_points: int,
    expected_response_ms: int,
) -> None:
    """Correct answers earn 100-200 points while incorrect answers earn zero."""
    result = calculate_score(
        correct_answer="alleviate",
        submitted_answer=submitted_answer,
        opens_at=OPENS_AT,
        closes_at=CLOSES_AT,
        submitted_at=submitted_at,
    )

    assert result.awarded_points == expected_points
    assert result.response_ms == expected_response_ms


def test_calculate_score_rejects_an_answer_after_the_round_closes() -> None:
    """The service does not score timestamps outside the round's open window."""
    with pytest.raises(ScoringWindowError):
        calculate_score(
            correct_answer="alleviate",
            submitted_answer="alleviate",
            opens_at=OPENS_AT,
            closes_at=CLOSES_AT,
            submitted_at=CLOSES_AT + timedelta(milliseconds=1),
        )
