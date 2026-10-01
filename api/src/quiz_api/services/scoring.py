"""Pure, server-timestamped scoring rules for vocabulary answers."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

BASE_POINTS: Final[int] = 100
MAX_SPEED_BONUS: Final[int] = 100


class ScoringWindowError(ValueError):
    """Raised when timestamps cannot describe a valid open quiz round."""


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """The correctness, response time, and awarded points for one answer."""

    awarded_points: int
    is_correct: bool
    response_ms: int


def calculate_score(
    *,
    correct_answer: str,
    submitted_answer: str,
    opens_at: datetime,
    closes_at: datetime,
    submitted_at: datetime,
) -> ScoreResult:
    """Score an answer using the authoritative server-observed timestamps."""
    round_duration_ms = duration_ms(opens_at, closes_at)
    response_ms = duration_ms(opens_at, submitted_at)
    if submitted_at > closes_at:
        message = "An answer cannot be scored after the round closes."
        raise ScoringWindowError(message)

    is_correct = normalize_answer(submitted_answer) == normalize_answer(correct_answer)
    if not is_correct:
        return ScoreResult(awarded_points=0, is_correct=False, response_ms=response_ms)

    remaining_ms = duration_ms(submitted_at, closes_at)
    speed_bonus = (MAX_SPEED_BONUS * remaining_ms) // round_duration_ms
    return ScoreResult(
        awarded_points=BASE_POINTS + speed_bonus,
        is_correct=True,
        response_ms=response_ms,
    )


def duration_ms(start: datetime, end: datetime) -> int:
    """Return a non-negative, millisecond precision duration between timestamps."""
    duration = end - start
    milliseconds = (
        duration.days * 86_400_000 + (duration.seconds * 1000) + (duration.microseconds // 1000)
    )
    if milliseconds < 0:
        message = "Round timestamps must be chronological."
        raise ScoringWindowError(message)
    return milliseconds


def normalize_answer(answer: str) -> str:
    """Normalize a selected vocabulary option before equality comparison."""
    return answer.strip().casefold()
