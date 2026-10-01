"""Tests for pure host round-transition rules and event payloads."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from quiz_api.database.models import RoundStatus
from quiz_api.services.exceptions import InvalidRoundDurationError
from quiz_api.services.rounds import round_event_payload, validate_round_duration


def test_round_duration_is_bounded_for_predictable_demo_rounds() -> None:
    """Hosts may open short rounds but cannot create unbounded timers."""
    validate_round_duration(1)
    validate_round_duration(300)

    with pytest.raises(InvalidRoundDurationError):
        validate_round_duration(0)
    with pytest.raises(InvalidRoundDurationError):
        validate_round_duration(301)


def test_round_event_payload_contains_authoritative_timestamps() -> None:
    """Event consumers receive versioned state rather than client-supplied timing."""
    opens_at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    closes_at = opens_at + timedelta(seconds=30)

    payload = round_event_payload(
        UUID("10000000-0000-0000-0000-000000000001"),
        RoundStatus.OPEN,
        opens_at,
        closes_at,
    )

    assert payload == {
        "closes_at": "2026-10-01T12:00:30+00:00",
        "event_version": 1,
        "opens_at": "2026-10-01T12:00:00+00:00",
        "round_id": "10000000-0000-0000-0000-000000000001",
        "status": "open",
    }
