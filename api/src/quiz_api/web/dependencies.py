"""Typed FastAPI dependencies for application-owned resources."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from quiz_api.infrastructure.resources import ApplicationResources


def get_resources(request: Request) -> ApplicationResources:
    """Return initialized application resources or fail as temporarily unavailable."""
    resources = getattr(request.app.state, "resources", None)
    if not isinstance(resources, ApplicationResources):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application resources are not available.",
        )
    return resources


ResourcesDependency = Annotated[ApplicationResources, Depends(get_resources)]


async def get_db_session(resources: ResourcesDependency) -> AsyncIterator[AsyncSession]:
    """Yield a session that always closes and rolls back uncommitted work."""
    async with resources.session_factory() as session:
        yield session


async def get_redis(resources: ResourcesDependency) -> Redis:
    """Return the lifecycle-owned asynchronous Redis client."""
    return resources.redis
