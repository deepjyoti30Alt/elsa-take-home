"""Tests for guest join input normalization and credential generation."""

import pytest

from quiz_api.database.models import QuizStatus
from quiz_api.services.exceptions import InvalidJoinError, QuizUnavailableError
from quiz_api.services.participation import (
    create_token_hash,
    ensure_new_participant_join_allowed,
    normalize_display_name,
    normalize_join_key,
)


def test_join_inputs_are_trimmed_before_persistence() -> None:
    """The same visible guest and idempotency values normalize predictably."""
    assert normalize_display_name("  Ada  ") == "Ada"
    assert normalize_join_key("  request-123  ") == "request-123"


@pytest.mark.parametrize("value", ["", " " * 81])
def test_invalid_display_names_are_rejected(value: str) -> None:
    """Guests cannot create blank or overlong names."""
    with pytest.raises(InvalidJoinError):
        normalize_display_name(value)


@pytest.mark.parametrize("value", ["", " " * 256])
def test_invalid_join_keys_are_rejected(value: str) -> None:
    """The idempotency key must remain within the durable-column limit."""
    with pytest.raises(InvalidJoinError):
        normalize_join_key(value)


def test_token_hashes_are_non_reversible_and_unique_per_join() -> None:
    """New guests receive independent credential references rather than raw tokens."""
    first_hash = create_token_hash()
    second_hash = create_token_hash()

    assert len(first_hash) == 64
    assert first_hash != second_hash


@pytest.mark.parametrize("status", [QuizStatus.ACTIVE, QuizStatus.COMPLETED])
def test_new_participants_cannot_join_after_a_quiz_starts(status: QuizStatus) -> None:
    """Only an existing idempotent join may be recovered after the host begins a quiz."""
    with pytest.raises(QuizUnavailableError, match="participation is closed"):
        ensure_new_participant_join_allowed(status)
