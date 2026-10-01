"""HTTP endpoints for quiz participant joins."""

from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, status

from quiz_api.web.api.quizzes.dependencies import (
    ParticipationServiceDependency,
    TokenServiceDependency,
)
from quiz_api.web.api.quizzes.schemas import JoinParticipantRequest, JoinParticipantResponse

router = APIRouter(prefix="/quizzes", tags=["participants"])


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
