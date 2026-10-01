"""Structured logging configuration and secret redaction."""

import logging
from collections.abc import Mapping
from typing import Final

import structlog
from structlog.types import EventDict, WrappedLogger

SENSITIVE_LOG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "authorization",
        "cookie",
        "host_demo_token",
        "jwt_signing_key",
        "password",
        "stream_token",
        "token",
    },
)
REDACTED_VALUE: Final[str] = "[REDACTED]"


def redact_sensitive_values(
    _: WrappedLogger,
    __: str,
    event_dict: EventDict,
) -> EventDict:
    """Replace sensitive values before an event is rendered or exported."""
    for key, value in event_dict.items():
        if key.lower() in SENSITIVE_LOG_KEYS:
            event_dict[key] = REDACTED_VALUE
        elif isinstance(value, Mapping):
            event_dict[key] = redact_mapping(value)
    return event_dict


def redact_mapping(values: Mapping[object, object]) -> dict[object, object]:
    """Return a recursively redacted mapping for nested structured fields."""
    redacted: dict[object, object] = {}
    for key, value in values.items():
        if isinstance(key, str) and key.lower() in SENSITIVE_LOG_KEYS:
            redacted[key] = REDACTED_VALUE
        elif isinstance(value, Mapping):
            redacted[key] = redact_mapping(value)
        else:
            redacted[key] = value
    return redacted


def configure_logging(log_level: str) -> None:
    """Configure JSON logging for application and third-party log records."""
    logging.basicConfig(format="%(message)s", level=log_level, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_sensitive_values,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
