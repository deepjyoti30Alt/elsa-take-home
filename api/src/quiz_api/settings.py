"""Typed application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Configuration needed by database tools outside the running API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QUIZ_API_",
        extra="ignore",
    )

    database_url: str

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Require the async PostgreSQL driver used by the application."""
        if not value.startswith("postgresql+asyncpg://"):
            message = "database_url must use the postgresql+asyncpg:// scheme"
            raise ValueError(message)
        return value


class Settings(DatabaseSettings):
    """Validated runtime configuration for the quiz API."""

    environment: str = "local"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    cors_allowed_origins: str = "http://localhost:3000"

    redis_url: str = "redis://localhost:6379/0"
    jwt_signing_key: SecretStr = Field(min_length=32)
    host_demo_token: SecretStr = Field(min_length=32)

    participant_token_ttl_seconds: int = Field(default=14_400, gt=0)
    stream_token_ttl_seconds: int = Field(default=300, gt=0)
    leaderboard_tick_ms: int = Field(default=250, ge=250, le=500)
    full_leaderboard_limit: int = Field(default=500, gt=0)
    compact_leaderboard_limit: int = Field(default=50, gt=0)
    join_rate_limit_per_minute: int = Field(default=10, gt=0, le=100)
    answer_rate_limit_per_minute: int = Field(default=30, gt=0, le=300)
    outbox_relay_batch_size: int = Field(default=100, gt=0, le=1000)
    outbox_relay_poll_ms: int = Field(default=250, ge=100, le=10_000)
    outbox_relay_retry_max_seconds: int = Field(default=30, ge=1, le=300)
    sse_heartbeat_seconds: int = Field(default=15, ge=5, le=60)
    sse_queue_size: int = Field(default=100, ge=10, le=1000)

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        """Require a Redis URL that the async client can connect to."""
        if not value.startswith(("redis://", "rediss://")):
            message = "redis_url must use the redis:// or rediss:// scheme"
            raise ValueError(message)
        return value

    @property
    def cors_origins(self) -> tuple[str, ...]:
        """Return configured CORS origins as normalized, non-empty values."""
        return tuple(
            origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Create and cache validated application settings for the process."""
    return Settings()  # type: ignore[call-arg]  # Required values are loaded from the environment.


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    """Create settings required by Alembic without requiring API secrets."""
    return DatabaseSettings()  # type: ignore[call-arg]  # Required values are loaded from the environment.
