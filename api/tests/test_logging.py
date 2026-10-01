"""Tests for structured-log secret redaction."""

from structlog.types import EventDict

from quiz_api.logging import REDACTED_VALUE, redact_sensitive_values


def test_redact_sensitive_values_covers_top_level_and_nested_fields() -> None:
    """Tokens are removed before a structured event reaches a log sink."""
    event: EventDict = {
        "event": "stream_connected",
        "stream_token": "do-not-log-me",
        "request": {"authorization": "Bearer do-not-log-me"},
    }

    redacted = redact_sensitive_values(None, "info", event)

    assert redacted["stream_token"] == REDACTED_VALUE
    assert redacted["request"] == {"authorization": REDACTED_VALUE}
