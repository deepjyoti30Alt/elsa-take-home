"""Signed participant and SSE stream tokens scoped to one quiz."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

import jwt
from jwt import InvalidTokenError as JwtInvalidTokenError

from quiz_api.database.models import Participant
from quiz_api.settings import Settings

JWT_ALGORITHM: Final[str] = "HS256"
PARTICIPANT_TOKEN_PURPOSE: Final[str] = "participant"  # noqa: S105 - JWT claim label.
STREAM_TOKEN_PURPOSE: Final[str] = "stream"  # noqa: S105 - JWT claim label.


class TokenValidationError(ValueError):
    """Raised when a signed token is expired, malformed, or wrongly scoped."""


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """Validated token claims available to API authorization code."""

    participant_id: UUID
    purpose: Literal["participant", "stream"]
    quiz_id: UUID


class TokenService:
    """Issue and validate short-lived JWTs for quiz-scoped guest access."""

    def __init__(self, settings: Settings) -> None:
        """Use the configured signing secret and token lifetimes."""
        self._participant_ttl = timedelta(seconds=settings.participant_token_ttl_seconds)
        self._signing_key = settings.jwt_signing_key.get_secret_value()
        self._stream_ttl = timedelta(seconds=settings.stream_token_ttl_seconds)

    def issue_participant_token(
        self,
        participant: Participant,
        *,
        issued_at: datetime | None = None,
    ) -> str:
        """Issue a command token for a participant's entire quiz lifetime."""
        return self._issue(
            participant=participant,
            purpose=PARTICIPANT_TOKEN_PURPOSE,
            issued_at=issued_at,
            ttl=self._participant_ttl,
        )

    def issue_stream_token(
        self,
        participant: Participant,
        *,
        issued_at: datetime | None = None,
    ) -> str:
        """Issue a short-lived token that authorizes only an SSE connection."""
        return self._issue(
            participant=participant,
            purpose=STREAM_TOKEN_PURPOSE,
            issued_at=issued_at,
            ttl=self._stream_ttl,
        )

    def validate_participant_token(self, token: str, *, quiz_id: UUID) -> TokenClaims:
        """Validate a participant command token for one expected quiz."""
        return self._validate(token, expected_purpose=PARTICIPANT_TOKEN_PURPOSE, quiz_id=quiz_id)

    def validate_stream_token(self, token: str, *, quiz_id: UUID) -> TokenClaims:
        """Validate a stream-only token for one expected quiz."""
        return self._validate(token, expected_purpose=STREAM_TOKEN_PURPOSE, quiz_id=quiz_id)

    def _issue(
        self,
        *,
        participant: Participant,
        purpose: str,
        issued_at: datetime | None,
        ttl: timedelta,
    ) -> str:
        timestamp = issued_at or datetime.now(UTC)
        payload = {
            "exp": timestamp + ttl,
            "iat": timestamp,
            "purpose": purpose,
            "quiz_id": str(participant.quiz_id),
            "sub": str(participant.id),
        }
        return jwt.encode(payload, self._signing_key, algorithm=JWT_ALGORITHM)

    def _validate(
        self,
        token: str,
        *,
        expected_purpose: str,
        quiz_id: UUID,
    ) -> TokenClaims:
        try:
            payload = jwt.decode(token, self._signing_key, algorithms=[JWT_ALGORITHM])
            participant_id = UUID(str(payload["sub"]))
            token_quiz_id = UUID(str(payload["quiz_id"]))
            purpose = str(payload["purpose"])
        except (JwtInvalidTokenError, KeyError, TypeError, ValueError) as exception:
            message = "The supplied token is invalid or expired."
            raise TokenValidationError(message) from exception

        if purpose != expected_purpose or token_quiz_id != quiz_id:
            message = "The supplied token is not authorized for this resource."
            raise TokenValidationError(message)
        if purpose not in {PARTICIPANT_TOKEN_PURPOSE, STREAM_TOKEN_PURPOSE}:
            message = "The supplied token contains an unsupported purpose."
            raise TokenValidationError(message)
        claims_purpose: Literal["participant", "stream"] = (
            "participant" if purpose == PARTICIPANT_TOKEN_PURPOSE else "stream"
        )
        return TokenClaims(
            participant_id=participant_id,
            purpose=claims_purpose,
            quiz_id=token_quiz_id,
        )
