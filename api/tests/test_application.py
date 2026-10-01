"""Tests for FastAPI application construction."""

from httpx import ASGITransport, AsyncClient

from quiz_api.application import get_app


async def test_health_endpoint_reports_an_available_process() -> None:
    """The unauthenticated health endpoint returns the stable liveness payload."""
    transport = ASGITransport(app=get_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
