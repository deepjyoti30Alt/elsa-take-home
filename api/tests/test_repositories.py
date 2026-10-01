"""Tests for repository query conventions that affect leaderboard fairness."""

from quiz_api.database.repositories import leaderboard_ordering


def test_leaderboard_ordering_uses_all_documented_tie_breakers() -> None:
    """Ranking is score-first, then speed, then deterministic participant ID."""
    ordering = leaderboard_ordering()

    assert len(ordering) == 3
    assert str(ordering[0]) == "participant.total_score DESC"
    assert str(ordering[1]) == "participant.total_response_ms ASC"
    assert str(ordering[2]) == "participant.id ASC"
