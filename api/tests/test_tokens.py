"""Tests for quiz-scoped signed participant and stream tokens."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from quiz_api.database.models import Participant
from quiz_api.security.tokens import TokenService, TokenValidationError
from quiz_api.settings import Settings


def build_token_service() -> TokenService:
    """Create an isolated token service with explicit test settings."""
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+asyncpg://user:password@db.example.com/quiz",
            "host_demo_token": "b" * 32,
            "jwt_signing_key": "a" * 32,
        },
    )
    return TokenService(settings)


def build_participant() -> Participant:
    """Create an unsaved participant suitable for claim generation tests."""
    return Participant(
        display_name="Ada",
        id=uuid4(),
        join_key="test-join-key",
        quiz_id=uuid4(),
        token_hash="a" * 64,
    )


def test_participant_token_is_valid_only_for_its_quiz() -> None:
    """A command token carries the expected participant and quiz claims."""
    service = build_token_service()
    participant = build_participant()

    token = service.issue_participant_token(participant, issued_at=datetime.now(UTC))
    claims = service.validate_participant_token(token, quiz_id=participant.quiz_id)

    assert claims.participant_id == participant.id
    assert claims.purpose == "participant"
    with pytest.raises(TokenValidationError):
        service.validate_participant_token(token, quiz_id=uuid4())


def test_stream_token_cannot_authorize_participant_commands() -> None:
    """Stream URL credentials cannot be replayed against command endpoints."""
    service = build_token_service()
    participant = build_participant()

    token = service.issue_stream_token(participant, issued_at=datetime.now(UTC))

    with pytest.raises(TokenValidationError):
        service.validate_participant_token(token, quiz_id=participant.quiz_id)
    assert service.validate_stream_token(token, quiz_id=participant.quiz_id).purpose == "stream"


def test_expired_tokens_are_rejected() -> None:
    """JWT expiry prevents reuse after the configured lifetime passes."""
    service = build_token_service()
    participant = build_participant()
    expired_at = datetime.now(UTC) - timedelta(days=1)

    token = service.issue_stream_token(participant, issued_at=expired_at)

    with pytest.raises(TokenValidationError):
        service.validate_stream_token(token, quiz_id=participant.quiz_id)
