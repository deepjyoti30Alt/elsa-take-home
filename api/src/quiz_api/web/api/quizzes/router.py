"""HTTP endpoints for quiz participant joins."""

from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, status

from quiz_api.web.api.quizzes.dependencies import (
    ParticipationServiceDependency,
    QuizSnapshotServiceDependency,
    TokenServiceDependency,
)
from quiz_api.web.api.quizzes.schemas import (
    JoinParticipantRequest,
    JoinParticipantResponse,
    QuestionSnapshotResponse,
    QuizSnapshotResponse,
    RoundSnapshotResponse,
)

router = APIRouter(prefix="/quizzes", tags=["participants"])


@router.get("/{quiz_id}", response_model=QuizSnapshotResponse, tags=["quizzes"])
async def get_quiz_snapshot(
    quiz_id: UUID,
    snapshot_service: QuizSnapshotServiceDependency,
) -> QuizSnapshotResponse:
    """Return client-visible quiz state without exposing answer keys."""
    snapshot = await snapshot_service.get_snapshot(quiz_id)
    current_round = None
    if snapshot.current_round is not None:
        current_round = RoundSnapshotResponse(
            closes_at=snapshot.current_round.closes_at,
            id=snapshot.current_round.id,
            opens_at=snapshot.current_round.opens_at,
            question=QuestionSnapshotResponse(
                options=snapshot.current_round.question.options,
                prompt=snapshot.current_round.question.prompt,
            ),
            status=snapshot.current_round.status,
        )
    return QuizSnapshotResponse(
        current_round=current_round,
        id=snapshot.id,
        status=snapshot.status,
    )


@router.post(
    "/{quiz_id}/participants",
    response_model=JoinParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def join_participant(
    quiz_id: UUID,
    request: JoinParticipantRequest,
    participation_service: ParticipationServiceDependency,
    token_service: TokenServiceDependency,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JoinParticipantResponse:
    """Create or recover a guest participant for one quiz-scoped idempotency key."""
    join_result = await participation_service.join_quiz(
        display_name=request.display_name,
        join_key=idempotency_key or str(uuid4()),
        quiz_id=quiz_id,
    )
    participant_token = token_service.issue_participant_token(join_result.participant)
    stream_token = token_service.issue_stream_token(join_result.participant)
    stream_query = urlencode({"stream_token": stream_token})
    return JoinParticipantResponse(
        participant_id=join_result.participant.id,
        participant_token=participant_token,
        quiz_id=quiz_id,
        stream_url=f"/v1/quizzes/{quiz_id}/events?{stream_query}",
    )
