"""Transactional answer acceptance for host-paced live quiz rounds."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.database.models import (
    OutboxEvent,
    OutboxEventType,
    RoundStatus,
    ScoreLedgerEntry,
    ScoreReason,
)
from quiz_api.database.repositories import (
    AnswerRepository,
    OutboxRepository,
    ParticipantRepository,
    QuizRepository,
)
from quiz_api.services.database_clock import get_database_clock
from quiz_api.services.exceptions import (
    DuplicateAnswerError,
    ParticipantNotFoundError,
    RoundNotFoundError,
    RoundNotOpenError,
)
from quiz_api.services.scoring import ScoreResult, calculate_score, normalize_answer

ANSWER_ACCEPTED_EVENT_VERSION: Final[int] = 1


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """Authoritative result returned after a successful answer transaction."""

    awarded_points: int
    is_correct: bool
    is_replay: bool
    response_ms: int
    submission_id: UUID
    total_response_ms: int
    total_score: int


class AnswerService:
    """Commit scoring, totals, audit entries, and outbox events atomically."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to one caller-owned asynchronous database session."""
        self._answers = AnswerRepository(session)
        self._outbox = OutboxRepository(session)
        self._participants = ParticipantRepository(session)
        self._quizzes = QuizRepository(session)
        self._session = session

    async def submit_answer(
        self,
        *,
        answer: str,
        participant_id: UUID,
        quiz_id: UUID,
        round_id: UUID,
    ) -> AnswerResult:
        """Accept one answer only when the database clock shows the round is open."""
        async with self._session.begin():
            participant = await self._participants.get_participant(quiz_id, participant_id)
            if participant is None:
                raise ParticipantNotFoundError

            round_ = await self._quizzes.get_round_for_share(quiz_id, round_id)
            if round_ is None:
                raise RoundNotFoundError
            submitted_at = await get_database_clock(self._session)
            opens_at, closes_at = ensure_round_is_open(
                round_.status,
                round_.opens_at,
                round_.closes_at,
                submitted_at,
            )

            question = await self._quizzes.get_question(round_.question_id)
            if question is None:
                message = "Round question was not available."
                raise RuntimeError(message)
            score = calculate_score(
                correct_answer=question.correct_answer,
                submitted_answer=answer,
                opens_at=opens_at,
                closes_at=closes_at,
                submitted_at=submitted_at,
            )
            submission = await self._answers.create_submission_if_absent(
                answer=answer,
                awarded_points=score.awarded_points,
                is_correct=score.is_correct,
                participant_id=participant.id,
                response_ms=score.response_ms,
                round_id=round_.id,
                submitted_at=submitted_at,
            )
            if submission is None:
                return await self._get_duplicate_result(
                    answer=answer,
                    participant_id=participant_id,
                    quiz_id=quiz_id,
                    round_id=round_id,
                )

            total_score, total_response_ms = await self._participants.apply_score(
                participant_id=participant.id,
                points=score.awarded_points,
                response_ms=score.response_ms,
            )
            if score.awarded_points > 0:
                self._session.add(
                    ScoreLedgerEntry(
                        participant_id=participant.id,
                        points=score.awarded_points,
                        reason=ScoreReason.CORRECT_ANSWER,
                        round_id=round_.id,
                    ),
                )
            sequence = await self._outbox.allocate_sequence(quiz_id)
            self._outbox.add_event(
                OutboxEvent(
                    payload=answer_accepted_payload(
                        participant_id=participant.id,
                        score=score,
                        total_response_ms=total_response_ms,
                        total_score=total_score,
                    ),
                    quiz_id=quiz_id,
                    seq=sequence,
                    type=OutboxEventType.ANSWER_ACCEPTED,
                ),
            )
            await self._session.flush()
            return AnswerResult(
                awarded_points=score.awarded_points,
                is_correct=score.is_correct,
                is_replay=False,
                response_ms=score.response_ms,
                submission_id=submission.id,
                total_response_ms=total_response_ms,
                total_score=total_score,
            )

    async def _get_duplicate_result(
        self,
        *,
        answer: str,
        participant_id: UUID,
        quiz_id: UUID,
        round_id: UUID,
    ) -> AnswerResult:
        """Return a same-answer replay or reject an attempt to alter an answer."""
        existing_submission = await self._answers.get_submission(participant_id, round_id)
        refreshed_participant = await self._participants.get_participant(quiz_id, participant_id)
        if existing_submission is None or refreshed_participant is None:
            message = "The prior answer was not available after a duplicate submission."
            raise RuntimeError(message)
        if not is_same_answer_retry(existing_submission.answer, answer):
            message = "A different answer was already submitted for this round."
            raise DuplicateAnswerError(message)
        return AnswerResult(
            awarded_points=existing_submission.awarded_points,
            is_correct=existing_submission.is_correct,
            is_replay=True,
            response_ms=existing_submission.response_ms,
            submission_id=existing_submission.id,
            total_response_ms=refreshed_participant.total_response_ms,
            total_score=refreshed_participant.total_score,
        )


def ensure_round_is_open(
    status: RoundStatus,
    opens_at: datetime | None,
    closes_at: datetime | None,
    submitted_at: datetime,
) -> tuple[datetime, datetime]:
    """Reject answers unless the authoritative database clock is within the window."""
    if (
        status is not RoundStatus.OPEN
        or opens_at is None
        or closes_at is None
        or submitted_at < opens_at
        or submitted_at >= closes_at
    ):
        message = "This round is not accepting answers."
        raise RoundNotOpenError(message)
    return opens_at, closes_at


def answer_accepted_payload(
    *,
    participant_id: UUID,
    score: ScoreResult,
    total_response_ms: int,
    total_score: int,
) -> dict[str, bool | int | str]:
    """Build the versioned durable payload consumed by projection workers."""
    return {
        "event_version": ANSWER_ACCEPTED_EVENT_VERSION,
        "is_correct": score.is_correct,
        "participant_id": str(participant_id),
        "response_ms": score.response_ms,
        "total_response_ms": total_response_ms,
        "total_score": total_score,
    }


def is_same_answer_retry(existing_answer: str, retried_answer: str) -> bool:
    """Compare answers with the same normalization used by scoring."""
    return normalize_answer(existing_answer) == normalize_answer(retried_answer)
