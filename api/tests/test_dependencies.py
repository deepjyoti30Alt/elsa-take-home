"""Tests for typed HTTP resource dependencies."""

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from quiz_api.application import get_app
from quiz_api.web.dependencies import get_db_session, get_redis, get_resources
from tests.test_application import build_test_settings


def make_request(app: FastAPI) -> Request:
    """Create the smallest ASGI request scope needed by dependencies."""
    return Request(
        {
            "app": app,
            "headers": [],
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "type": "http",
        },
    )


def test_get_resources_returns_503_before_lifespan_starts() -> None:
    """Requests cannot use dependencies before application startup completes."""
    with pytest.raises(HTTPException) as exception_info:
        get_resources(make_request(FastAPI()))

    assert exception_info.value.status_code == 503


async def test_dependencies_return_lifespan_owned_resources() -> None:
    """Database and Redis dependencies reuse clients owned by the application."""
    app = get_app(build_test_settings())

    async with app.router.lifespan_context(app):
        resources = get_resources(make_request(app))
        assert await get_redis(resources) is resources.redis

        async for session in get_db_session(resources):
            assert session.bind is resources.engine
