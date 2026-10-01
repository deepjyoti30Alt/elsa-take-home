"""Tests for FastAPI application construction."""

from httpx import ASGITransport, AsyncClient

from quiz_api.application import get_app
from quiz_api.settings import Settings


def build_test_settings() -> Settings:
    """Create explicit, non-secret settings for application tests."""
    return Settings.model_validate(
        {
            "database_url": "postgresql+asyncpg://user:password@db.example.com/quiz",
            "host_demo_token": "b" * 32,
            "jwt_signing_key": "a" * 32,
        },
    )


async def test_health_endpoint_reports_an_available_process() -> None:
    """The unauthenticated health endpoint returns the stable liveness payload."""
    transport = ASGITransport(app=get_app(build_test_settings()))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_endpoint_returns_a_safe_correlation_id() -> None:
    """A request receives a generated ID when the client does not supply one."""
    transport = ASGITransport(app=get_app(build_test_settings()))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.headers["X-Request-ID"]
