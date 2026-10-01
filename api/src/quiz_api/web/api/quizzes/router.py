"""HTTP endpoints for quiz participant joins."""

from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, status

from quiz_api.web.api.quizzes.dependencies import (
    AnswerServiceDependency,
    AuthenticatedParticipantDependency,
    LeaderboardReadServiceDependency,
    ParticipationServiceDependency,
    QuizSnapshotServiceDependency,
    TokenServiceDependency,
)
from quiz_api.web.api.quizzes.schemas import (
    JoinParticipantRequest,
    JoinParticipantResponse,
    LeaderboardEntryResponse,
    LeaderboardPageResponse,
    QuestionSnapshotResponse,
    QuizSnapshotResponse,
    RoundSnapshotResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
)

router = APIRouter(prefix="/quizzes", tags=["participants"])


@router.post(
    "/{quiz_id}/rounds/{round_id}/answers",
    response_model=SubmitAnswerResponse,
    tags=["answers"],
)
async def submit_answer(
    quiz_id: UUID,
    round_id: UUID,
    request: SubmitAnswerRequest,
    participant: AuthenticatedParticipantDependency,
    answer_service: AnswerServiceDependency,
) -> SubmitAnswerResponse:
    """Accept a participant's first answer for an open round, or return its replay."""
    result = await answer_service.submit_answer(
        answer=request.answer,
        participant_id=participant.participant_id,
        quiz_id=quiz_id,
        round_id=round_id,
    )
    return SubmitAnswerResponse(
        awarded_points=result.awarded_points,
        is_correct=result.is_correct,
        is_replay=result.is_replay,
        response_ms=result.response_ms,
        submission_id=result.submission_id,
        total_response_ms=result.total_response_ms,
        total_score=result.total_score,
    )


@router.get("/{quiz_id}/leaderboard", response_model=LeaderboardPageResponse, tags=["leaderboard"])
async def get_leaderboard(
    quiz_id: UUID,
    leaderboard_service: LeaderboardReadServiceDependency,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> LeaderboardPageResponse:
    """Return a paginated leaderboard using the documented tie-break ordering."""
    page = await leaderboard_service.get_page(limit=limit, offset=offset, quiz_id=quiz_id)
    return LeaderboardPageResponse(
        entries=tuple(
            LeaderboardEntryResponse(
                display_name=entry.display_name,
                participant_id=entry.participant_id,
                rank=entry.rank,
                total_response_ms=entry.total_response_ms,
                total_score=entry.total_score,
            )
            for entry in page.entries
        ),
        limit=page.limit,
        offset=page.offset,
        total=page.total,
    )


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
