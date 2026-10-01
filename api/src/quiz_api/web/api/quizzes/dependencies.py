"""FastAPI dependencies for quiz domain services and token handling."""

from hmac import compare_digest
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.security.tokens import TokenClaims, TokenService, TokenValidationError
from quiz_api.services.answers import AnswerService
from quiz_api.services.event_streams import QuizEventBroker
from quiz_api.services.leaderboard_cache import (
    RedisLeaderboardReader,
    RedisLeaderboardReadTransport,
)
from quiz_api.services.leaderboard_reads import LeaderboardReadService
from quiz_api.services.outbox_relay import RedisEventTransport, RedisLeaderboardProjection
from quiz_api.services.participation import ParticipationService
from quiz_api.services.quiz_reset import QuizResetService
from quiz_api.services.rounds import RoundControlService
from quiz_api.services.snapshots import QuizSnapshotService
from quiz_api.settings import Settings
from quiz_api.web.dependencies import ResourcesDependency, get_db_session, get_redis
from quiz_api.web.rate_limit import FixedWindowRateLimiter

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
    redis: Annotated[RedisLeaderboardReadTransport, Depends(get_redis)],
) -> LeaderboardReadService:
    """Create a leaderboard read service bound to the request database session."""
    return LeaderboardReadService(session, RedisLeaderboardReader(redis))


async def get_answer_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AnswerService:
    """Create an answer command service bound to the request database session."""
    return AnswerService(session)


async def get_round_control_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RoundControlService:
    """Create a host round-control service bound to the request database session."""
    return RoundControlService(session)


async def get_quiz_reset_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[RedisEventTransport, Depends(get_redis)],
) -> QuizResetService:
    """Create the host-only reset service with durable and cache access."""
    return QuizResetService(session, RedisLeaderboardProjection(redis))


def require_host_token(
    request: Request,
    supplied_token: Annotated[str | None, Header(alias="X-Host-Token")] = None,
) -> None:
    """Authorize demo host controls with a constant-time shared-secret comparison."""
    settings = cast(Settings, request.app.state.settings)
    expected_token = settings.host_demo_token.get_secret_value()
    if supplied_token is None or not compare_digest(supplied_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A valid host token is required.",
        )


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


def get_authenticated_stream(
    quiz_id: UUID,
    stream_token: Annotated[str, Query(min_length=1)],
    token_service: Annotated[TokenService, Depends(get_token_service)],
) -> TokenClaims:
    """Validate a short-lived stream token supplied in the native EventSource URL."""
    try:
        return token_service.validate_stream_token(stream_token, quiz_id=quiz_id)
    except TokenValidationError as exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The stream token is invalid or expired.",
        ) from exception


def get_stream_broker(resources: ResourcesDependency) -> QuizEventBroker:
    """Return the lifecycle-owned shared Redis subscription broker."""
    return resources.event_broker


async def enforce_join_rate_limit(request: Request) -> None:
    """Bound unauthenticated participant joins per source address."""
    settings = cast(Settings, request.app.state.settings)
    limiter = get_rate_limiter(request)
    await limiter.check(
        key=f"join:{get_client_address(request)}",
        limit=settings.join_rate_limit_per_minute,
        window_seconds=60,
    )


async def enforce_answer_rate_limit(
    request: Request,
    participant: Annotated[TokenClaims, Depends(get_authenticated_participant)],
) -> None:
    """Bound answer submissions per authenticated participant and source address."""
    settings = cast(Settings, request.app.state.settings)
    limiter = get_rate_limiter(request)
    await limiter.check(
        key=f"answer:{participant.participant_id}:{get_client_address(request)}",
        limit=settings.answer_rate_limit_per_minute,
        window_seconds=60,
    )


def get_rate_limiter(request: Request) -> FixedWindowRateLimiter:
    """Return the application-owned limiter or fail safely during misconfiguration."""
    limiter = getattr(request.app.state, "rate_limiter", None)
    if not isinstance(limiter, FixedWindowRateLimiter):
        raise RuntimeError("The application rate limiter is not configured.")
    return limiter


def get_client_address(request: Request) -> str:
    """Return the immediate peer address for the local deployment rate limit key."""
    return request.client.host if request.client is not None else "unknown"


ParticipationServiceDependency = Annotated[ParticipationService, Depends(get_participation_service)]
LeaderboardReadServiceDependency = Annotated[
    LeaderboardReadService, Depends(get_leaderboard_read_service)
]
AnswerServiceDependency = Annotated[AnswerService, Depends(get_answer_service)]
AuthenticatedParticipantDependency = Annotated[TokenClaims, Depends(get_authenticated_participant)]
AuthenticatedStreamDependency = Annotated[TokenClaims, Depends(get_authenticated_stream)]
HostAuthorizationDependency = Annotated[None, Depends(require_host_token)]
JoinRateLimitDependency = Annotated[None, Depends(enforce_join_rate_limit)]
QuizSnapshotServiceDependency = Annotated[QuizSnapshotService, Depends(get_quiz_snapshot_service)]
AnswerRateLimitDependency = Annotated[None, Depends(enforce_answer_rate_limit)]
RoundControlServiceDependency = Annotated[RoundControlService, Depends(get_round_control_service)]
QuizResetServiceDependency = Annotated[QuizResetService, Depends(get_quiz_reset_service)]
StreamBrokerDependency = Annotated[QuizEventBroker, Depends(get_stream_broker)]
TokenServiceDependency = Annotated[TokenService, Depends(get_token_service)]
