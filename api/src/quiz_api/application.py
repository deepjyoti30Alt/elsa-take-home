"""FastAPI application construction."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal, cast

from fastapi import FastAPI, Response, status
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel

from quiz_api.infrastructure.resources import create_application_resources
from quiz_api.logging import configure_logging
from quiz_api.observability import metrics_payload
from quiz_api.settings import Settings, get_settings
from quiz_api.web.api.router import API_PREFIX, api_router
from quiz_api.web.dependencies import ResourcesDependency
from quiz_api.web.errors import register_exception_handlers
from quiz_api.web.middleware.request_context import RequestContextMiddleware
from quiz_api.web.rate_limit import FixedWindowRateLimiter
from quiz_api.web.readiness import ReadinessResources, check_readiness


class HealthResponse(BaseModel):
    """Response returned when the process is alive."""

    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    """Dependency-specific readiness state used by load balancers and operators."""

    database: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]
    status: Literal["ok", "unavailable"]


def get_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the quiz API application."""
    application_settings = settings or get_settings()
    configure_logging(application_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Create process resources and dispose of them on shutdown."""
        resources = create_application_resources(application_settings)
        app.state.resources = resources
        resources.workers.start(
            lambda: resources.outbox_relay.run_forever(
                batch_size=application_settings.outbox_relay_batch_size,
                poll_interval_seconds=application_settings.outbox_relay_poll_ms / 1000,
                retry_max_seconds=float(application_settings.outbox_relay_retry_max_seconds),
            ),
        )
        resources.workers.start(
            lambda: resources.leaderboard_ticker.run_forever(
                interval_seconds=application_settings.leaderboard_tick_ms / 1000,
            ),
        )
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
    app.state.rate_limiter = FixedWindowRateLimiter()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def get_health() -> HealthResponse:
        """Report that the API process is available."""
        return HealthResponse()

    @app.get("/metrics", include_in_schema=False)
    async def get_metrics() -> Response:
        """Expose Prometheus metrics without adding it to the public quiz API contract."""
        return Response(content=metrics_payload(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/ready", response_model=ReadinessResponse, tags=["operations"])
    async def get_readiness(resources: ResourcesDependency) -> Response:
        """Report readiness while distinguishing the database from Redis availability."""
        result = await check_readiness(cast(ReadinessResources, resources))
        response = ReadinessResponse(
            database="ok" if result.database_ready else "unavailable",
            redis="ok" if result.redis_ready else "unavailable",
            status="ok" if result.ready else "unavailable",
        )
        return Response(
            content=response.model_dump_json(),
            media_type="application/json",
            status_code=status.HTTP_200_OK if result.ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return app
