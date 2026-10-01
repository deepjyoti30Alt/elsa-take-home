"""Guest quiz participation and idempotent join behavior."""

from dataclasses import dataclass
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.database.models import Participant, QuizStatus
from quiz_api.database.repositories import ParticipantRepository, QuizRepository
from quiz_api.services.exceptions import InvalidJoinError, QuizNotFoundError, QuizUnavailableError


@dataclass(frozen=True, slots=True)
class JoinResult:
    """The durable result of a guest join operation."""

    created: bool
    participant: Participant


class ParticipationService:
    """Create quiz-scoped guests while making client retries safe."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to one caller-owned asynchronous database session."""
        self._session = session
        self._participants = ParticipantRepository(session)
        self._quizzes = QuizRepository(session)

    async def join_quiz(
        self,
        *,
        display_name: str,
        join_key: str,
        quiz_id: UUID,
    ) -> JoinResult:
        """Create or recover a guest participant for one idempotency key."""
        normalized_display_name = normalize_display_name(display_name)
        normalized_join_key = normalize_join_key(join_key)

        async with self._session.begin():
            quiz = await self._quizzes.get_quiz_for_update(quiz_id)
            if quiz is None:
                raise QuizNotFoundError
            existing_participant = await self._participants.get_by_join_key(
                quiz_id, normalized_join_key
            )
            if existing_participant is not None:
                return JoinResult(created=False, participant=existing_participant)
            ensure_new_participant_join_allowed(quiz.status)

            participant, created = await self._participants.create_or_get_by_join_key(
                display_name=normalized_display_name,
                join_key=normalized_join_key,
                quiz_id=quiz_id,
                token_hash=create_token_hash(),
            )
        return JoinResult(created=created, participant=participant)


def ensure_new_participant_join_allowed(status: QuizStatus) -> None:
    """Reject new participants once a host-paced quiz has started or finished."""
    if status is not QuizStatus.DRAFT:
        message = "Quiz participation is closed because the quiz has already started."
        raise QuizUnavailableError(message)


def normalize_display_name(display_name: str) -> str:
    """Validate and normalize a guest-visible display name."""
    normalized = display_name.strip()
    if not 1 <= len(normalized) <= 80:
        message = "Display names must contain between 1 and 80 characters."
        raise InvalidJoinError(message)
    return normalized


def normalize_join_key(join_key: str) -> str:
    """Validate an idempotency key used to deduplicate a guest join."""
    normalized = join_key.strip()
    if not 1 <= len(normalized) <= 255:
        message = "Join keys must contain between 1 and 255 characters."
        raise InvalidJoinError(message)
    return normalized


def create_token_hash() -> str:
    """Create an opaque non-reversible participant credential reference."""
    return sha256(token_urlsafe(32).encode("utf-8")).hexdigest()
