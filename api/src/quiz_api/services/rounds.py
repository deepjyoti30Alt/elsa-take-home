"""Host-controlled, lock-safe transitions for shared quiz rounds."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.database.models import OutboxEvent, OutboxEventType, QuizStatus, RoundStatus
from quiz_api.database.repositories import OutboxRepository, QuizRepository
from quiz_api.services.database_clock import get_database_clock
from quiz_api.services.exceptions import (
    InvalidRoundDurationError,
    QuizNotFoundError,
    QuizUnavailableError,
    RoundNotFoundError,
    RoundTransitionError,
)

MAX_ROUND_DURATION_SECONDS: Final[int] = 300
MIN_ROUND_DURATION_SECONDS: Final[int] = 1
ROUND_EVENT_VERSION: Final[int] = 1


@dataclass(frozen=True, slots=True)
class RoundTransitionResult:
    """Authoritative state returned after a host opens or closes a round."""

    closes_at: datetime
    opens_at: datetime
    round_id: UUID
    status: RoundStatus


class RoundControlService:
    """Open and close one shared round at a time for a host-paced quiz."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to one caller-owned asynchronous database session."""
        self._outbox = OutboxRepository(session)
        self._quizzes = QuizRepository(session)
        self._session = session

    async def open_round(
        self,
        *,
        duration_seconds: int,
        quiz_id: UUID,
        round_id: UUID,
    ) -> RoundTransitionResult:
        """Open a pending round and announce its authoritative timing window."""
        validate_round_duration(duration_seconds)
        async with self._session.begin():
            round_ = await self._quizzes.get_round_for_update(quiz_id, round_id)
            if round_ is None:
                raise RoundNotFoundError
            quiz = await self._quizzes.get_quiz_for_update(quiz_id)
            if quiz is None:
                raise QuizNotFoundError
            if quiz.status is QuizStatus.COMPLETED:
                raise QuizUnavailableError
            if quiz.current_round_id is not None or round_.status is not RoundStatus.PENDING:
                message = "The requested round cannot be opened in its current state."
                raise RoundTransitionError(message)

            opens_at = await get_database_clock(self._session)
            closes_at = opens_at + timedelta(seconds=duration_seconds)
            quiz.current_round_id = round_.id
            quiz.status = QuizStatus.ACTIVE
            round_.closes_at = closes_at
            round_.opens_at = opens_at
            round_.status = RoundStatus.OPEN
            sequence = await self._outbox.allocate_sequence(quiz_id)
            self._outbox.add_event(
                OutboxEvent(
                    payload=round_event_payload(round_.id, RoundStatus.OPEN, opens_at, closes_at),
                    quiz_id=quiz_id,
                    seq=sequence,
                    type=OutboxEventType.ROUND_OPENED,
                ),
            )
            await self._session.flush()
            return RoundTransitionResult(
                closes_at=closes_at,
                opens_at=opens_at,
                round_id=round_.id,
                status=round_.status,
            )

    async def close_round(self, *, quiz_id: UUID, round_id: UUID) -> RoundTransitionResult:
        """Close an open round after waiting for in-flight shared answer locks."""
        async with self._session.begin():
            round_ = await self._quizzes.get_round_for_update(quiz_id, round_id)
            if round_ is None:
                raise RoundNotFoundError
            quiz = await self._quizzes.get_quiz_for_update(quiz_id)
            if quiz is None:
                raise QuizNotFoundError
            if round_.status is not RoundStatus.OPEN or quiz.current_round_id != round_.id:
                message = "The requested round is not the open round for this quiz."
                raise RoundTransitionError(message)

            closed_at = await get_database_clock(self._session)
            if round_.opens_at is None:
                message = "An open round is missing its open timestamp."
                raise RuntimeError(message)
            quiz.current_round_id = None
            round_.closes_at = closed_at
            round_.status = RoundStatus.CLOSED
            sequence = await self._outbox.allocate_sequence(quiz_id)
            self._outbox.add_event(
                OutboxEvent(
                    payload=round_event_payload(
                        round_.id, RoundStatus.CLOSED, round_.opens_at, closed_at
                    ),
                    quiz_id=quiz_id,
                    seq=sequence,
                    type=OutboxEventType.ROUND_CLOSED,
                ),
            )
            await self._session.flush()
            return RoundTransitionResult(
                closes_at=closed_at,
                opens_at=round_.opens_at,
                round_id=round_.id,
                status=round_.status,
            )


def validate_round_duration(duration_seconds: int) -> None:
    """Require a bounded positive host-configured round duration."""
    if not MIN_ROUND_DURATION_SECONDS <= duration_seconds <= MAX_ROUND_DURATION_SECONDS:
        message = (
            f"Round duration must be between {MIN_ROUND_DURATION_SECONDS} and "
            f"{MAX_ROUND_DURATION_SECONDS} seconds."
        )
        raise InvalidRoundDurationError(message)


def round_event_payload(
    round_id: UUID,
    status: RoundStatus,
    opens_at: datetime,
    closes_at: datetime,
) -> dict[str, int | str]:
    """Build the durable event payload consumed by stream publication workers."""
    return {
        "closes_at": closes_at.isoformat(),
        "event_version": ROUND_EVENT_VERSION,
        "opens_at": opens_at.isoformat(),
        "round_id": str(round_id),
        "status": status.value,
    }
