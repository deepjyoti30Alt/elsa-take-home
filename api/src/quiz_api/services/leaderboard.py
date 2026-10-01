"""Deterministic leaderboard ranking shared by API response projections."""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ParticipantStanding:
    """A participant's durable totals before rank projection."""

    display_name: str
    participant_id: UUID
    total_response_ms: int
    total_score: int


@dataclass(frozen=True, slots=True)
class RankedStanding:
    """A participant standing with a deterministic one-based leaderboard rank."""

    display_name: str
    participant_id: UUID
    rank: int
    total_response_ms: int
    total_score: int


def participant_standing_sort_key(standing: ParticipantStanding) -> tuple[int, int, str]:
    """Sort score descending, response time ascending, then ID ascending."""
    return (-standing.total_score, standing.total_response_ms, str(standing.participant_id))


def rank_standings(standings: Iterable[ParticipantStanding]) -> tuple[RankedStanding, ...]:
    """Return a fully ordered leaderboard with deterministic unique positions."""
    ordered_standings = sorted(standings, key=participant_standing_sort_key)
    return tuple(
        RankedStanding(
            display_name=standing.display_name,
            participant_id=standing.participant_id,
            rank=index,
            total_response_ms=standing.total_response_ms,
            total_score=standing.total_score,
        )
        for index, standing in enumerate(ordered_standings, start=1)
    )
