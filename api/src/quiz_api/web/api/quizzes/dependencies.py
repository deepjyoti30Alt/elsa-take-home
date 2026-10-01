"""FastAPI dependencies for quiz domain services and token handling."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.security.tokens import TokenClaims, TokenService, TokenValidationError
from quiz_api.services.answers import AnswerService
from quiz_api.services.leaderboard_reads import LeaderboardReadService
from quiz_api.services.participation import ParticipationService
from quiz_api.services.snapshots import QuizSnapshotService
from quiz_api.settings import Settings
from quiz_api.web.dependencies import get_db_session

participant_bearer_scheme = HTTPBearer(auto_error=False)


def get_token_service(request: Request) -> TokenService:
    """Create a token service from the settings captured by the application factory."""
    settings = cast(Settings, request.app.state.settings)
    return TokenService(settings)


async def get_participation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ParticipationService:
    """Create a participation service bound to the request database session."""
    return ParticipationService(session)


async def get_quiz_snapshot_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> QuizSnapshotService:
    """Create a snapshot read service bound to the request database session."""
    return QuizSnapshotService(session)


async def get_leaderboard_read_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LeaderboardReadService:
    """Create a leaderboard read service bound to the request database session."""
    return LeaderboardReadService(session)


async def get_answer_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AnswerService:
    """Create an answer command service bound to the request database session."""
    return AnswerService(session)


def get_authenticated_participant(
    quiz_id: UUID,
    token_service: Annotated[TokenService, Depends(get_token_service)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(participant_bearer_scheme),
    ],
) -> TokenClaims:
    """Validate a participant command token for the quiz addressed by the route."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A participant bearer token is required.",
        )
    try:
        return token_service.validate_participant_token(credentials.credentials, quiz_id=quiz_id)
    except TokenValidationError as exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The participant token is invalid or expired.",
        ) from exception


ParticipationServiceDependency = Annotated[ParticipationService, Depends(get_participation_service)]
LeaderboardReadServiceDependency = Annotated[
    LeaderboardReadService, Depends(get_leaderboard_read_service)
]
AnswerServiceDependency = Annotated[AnswerService, Depends(get_answer_service)]
AuthenticatedParticipantDependency = Annotated[TokenClaims, Depends(get_authenticated_participant)]
QuizSnapshotServiceDependency = Annotated[QuizSnapshotService, Depends(get_quiz_snapshot_service)]
TokenServiceDependency = Annotated[TokenService, Depends(get_token_service)]
