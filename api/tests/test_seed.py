"""Tests for deterministic demo quiz content."""

from quiz_api.seed import DEMO_QUESTIONS, DEMO_QUIZ_ID, demo_round_id


def test_demo_seed_content_has_unique_ids_and_valid_answers() -> None:
    """Every seeded question can be presented as a valid multiple-choice round."""
    assert DEMO_QUIZ_ID
    assert len(DEMO_QUESTIONS) == 5
    assert len({question.id for question in DEMO_QUESTIONS}) == len(DEMO_QUESTIONS)
    assert len({demo_round_id(question) for question in DEMO_QUESTIONS}) == len(DEMO_QUESTIONS)
    assert all(question.correct_answer in question.options for question in DEMO_QUESTIONS)
