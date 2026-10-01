"""Tests for deterministic leaderboard ranking."""

from uuid import UUID

from quiz_api.services.leaderboard import ParticipantStanding, rank_standings


def test_rankings_use_score_speed_and_participant_id_tie_breakers() -> None:
    """Every participant receives a reproducible unique position in the standings."""
    standings = (
        ParticipantStanding(
            display_name="Slow high scorer",
            participant_id=UUID("30000000-0000-0000-0000-000000000003"),
            total_response_ms=3000,
            total_score=200,
        ),
        ParticipantStanding(
            display_name="Fast high scorer",
            participant_id=UUID("10000000-0000-0000-0000-000000000001"),
            total_response_ms=1000,
            total_score=200,
        ),
        ParticipantStanding(
            display_name="Same totals, later ID",
            participant_id=UUID("20000000-0000-0000-0000-000000000002"),
            total_response_ms=1000,
            total_score=200,
        ),
        ParticipantStanding(
            display_name="Lower scorer",
            participant_id=UUID("40000000-0000-0000-0000-000000000004"),
            total_response_ms=1,
            total_score=199,
        ),
    )

    ranked = rank_standings(standings)

    assert [(standing.rank, standing.display_name) for standing in ranked] == [
        (1, "Fast high scorer"),
        (2, "Same totals, later ID"),
        (3, "Slow high scorer"),
        (4, "Lower scorer"),
    ]
