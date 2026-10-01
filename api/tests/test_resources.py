"""Tests for application resource lifecycle management."""

from quiz_api.application import get_app
from tests.test_application import build_test_settings


async def test_lifespan_creates_and_closes_application_resources() -> None:
    """Resource clients are owned by the app lifespan without network I/O."""
    app = get_app(build_test_settings())

    async with app.router.lifespan_context(app):
        resources = app.state.resources
        assert resources.engine is not None
        assert resources.redis is not None
