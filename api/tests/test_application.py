"""Tests for FastAPI application construction."""

from fastapi import FastAPI, HTTPException, Query
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


def build_error_test_app() -> FastAPI:
    """Create an application with routes that exercise global error handlers."""
    app = get_app(build_test_settings())

    @app.get("/expected-error")
    async def raise_expected_error() -> None:
        """Raise an HTTP error that should preserve its public message."""
        raise HTTPException(status_code=409, detail="An answer already exists.")

    @app.get("/validation-error")
    async def require_positive_number(value: int = Query(gt=0)) -> dict[str, int]:
        """Require a positive integer to exercise request validation."""
        return {"value": value}

    @app.get("/unexpected-error")
    async def raise_unexpected_error() -> None:
        """Raise an internal failure that must not leak implementation details."""
        message = "database password must never be returned"
        raise RuntimeError(message)

    return app


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


async def test_http_errors_use_a_consistent_public_envelope() -> None:
    """Expected, validation, and unexpected failures share safe error contracts."""
    transport = ASGITransport(app=build_error_test_app(), raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        expected_response = await client.get("/expected-error")
        validation_response = await client.get("/validation-error?value=0")
        unexpected_response = await client.get("/unexpected-error")

    assert expected_response.status_code == 409
    assert expected_response.json()["error"]["code"] == "conflict"
    assert expected_response.json()["error"]["message"] == "An answer already exists."
    assert expected_response.json()["error"]["correlation_id"]
    assert validation_response.status_code == 422
    assert validation_response.json()["error"]["code"] == "validation_error"
    assert unexpected_response.status_code == 500
    assert unexpected_response.json()["error"]["code"] == "internal_error"
    assert "password" not in unexpected_response.text


async def test_openapi_describes_the_versioned_api_boundary() -> None:
    """OpenAPI exposes stable service metadata and the `/v1` router route."""
    transport = ASGITransport(app=get_app(build_test_settings()))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        openapi_response = await client.get("/openapi.json")
        metadata_response = await client.get("/v1/")

    openapi = openapi_response.json()
    assert openapi_response.status_code == 200
    assert openapi["info"]["title"] == "Real-Time Vocabulary Quiz API"
    assert openapi["info"]["version"] == "0.1.0"
    assert "/v1/" in openapi["paths"]
    assert metadata_response.json() == {
        "api_version": "v1",
        "service": "real-time-vocabulary-quiz",
    }
