"""FastAPI dependencies for quiz domain services and token handling."""

from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.security.tokens import TokenService
from quiz_api.services.participation import ParticipationService
from quiz_api.settings import Settings
from quiz_api.web.dependencies import get_db_session


def get_token_service(request: Request) -> TokenService:
    """Create a token service from the settings captured by the application factory."""
    settings = cast(Settings, request.app.state.settings)
    return TokenService(settings)


async def get_participation_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ParticipationService:
    """Create a participation service bound to the request database session."""
    return ParticipationService(session)


ParticipationServiceDependency = Annotated[ParticipationService, Depends(get_participation_service)]
TokenServiceDependency = Annotated[TokenService, Depends(get_token_service)]
