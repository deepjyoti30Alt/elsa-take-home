"""FastAPI application construction."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response returned when the process is alive."""

    status: Literal["ok"] = "ok"


def get_app() -> FastAPI:
    """Create and configure the quiz API application."""
    app = FastAPI(
        title="Real-Time Vocabulary Quiz API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    @app.get("/health", response_model=HealthResponse, tags=["operations"])
    async def get_health() -> HealthResponse:
        """Report that the API process is available."""
        return HealthResponse()

    return app
