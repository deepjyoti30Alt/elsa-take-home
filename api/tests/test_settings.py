"""Tests for application settings validation."""

import pytest
from pydantic import ValidationError

from quiz_api.settings import Settings


def build_settings(**overrides: object) -> Settings:
    """Build valid settings, optionally replacing individual values."""
    values: dict[str, object] = {
        "database_url": "postgresql+asyncpg://user:password@db.example.com/quiz",
        "jwt_signing_key": "a" * 32,
        "host_demo_token": "b" * 32,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_settings_parse_comma_separated_cors_origins() -> None:
    """CORS origins are trimmed and empty values are discarded."""
    settings = build_settings(
        cors_allowed_origins="http://localhost:3000, https://quiz.example.com,",
    )

    assert settings.cors_origins == (
        "http://localhost:3000",
        "https://quiz.example.com",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "postgresql://user:password@db.example.com/quiz"),
        ("redis_url", "https://cache.example.com"),
    ],
)
def test_settings_reject_unsupported_connection_schemes(field: str, value: str) -> None:
    """Database and Redis URLs must target the configured async clients."""
    with pytest.raises(ValidationError):
        build_settings(**{field: value})
