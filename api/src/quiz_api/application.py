"""FastAPI application construction."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from quiz_api.infrastructure.resources import create_application_resources
from quiz_api.logging import configure_logging
from quiz_api.settings import Settings, get_settings
from quiz_api.web.api.router import API_PREFIX, api_router
from quiz_api.web.errors import register_exception_handlers
from quiz_api.web.middleware.request_context import RequestContextMiddleware


class HealthResponse(BaseModel):
    """Response returned when the process is alive."""

    status: Literal["ok"] = "ok"


def get_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the quiz API application."""
    application_settings = settings or get_settings()
    configure_logging(application_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Create process resources and dispose of them on shutdown."""
        resources = create_application_resources(application_settings)
        app.state.resources = resources
        try:
            yield
        finally:
            await resources.close()

    app = FastAPI(
        title="Real-Time Vocabulary Quiz API",
        version="0.1.0",
        summary="REST and SSE backend for host-paced live vocabulary quizzes.",
        description=(
            "The service provides durable quiz participation, scoring, and "
            "real-time leaderboard delivery."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = application_settings
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def get_health() -> HealthResponse:
        """Report that the API process is available."""
        return HealthResponse()

    return app
