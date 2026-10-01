"""Tests for versioned durable-to-wire event contracts."""

from datetime import UTC, datetime
from uuid import UUID

from quiz_api.database.models import OutboxEvent, OutboxEventType
from quiz_api.events import outbox_event_to_envelope, quiz_channel

QUIZ_ID = UUID("10000000-0000-0000-0000-000000000001")
PARTICIPANT_ID = UUID("20000000-0000-0000-0000-000000000002")


def test_answer_outbox_event_converts_to_a_versioned_wire_envelope() -> None:
    """The relay validates durable answer data before delivery workers consume it."""
    event = OutboxEvent(
        created_at=datetime(2026, 10, 1, 12, tzinfo=UTC),
        payload={
            "display_name": "Ada",
            "event_version": 1,
            "is_correct": True,
            "participant_id": str(PARTICIPANT_ID),
            "response_ms": 300,
            "total_response_ms": 300,
            "total_score": 195,
        },
        quiz_id=QUIZ_ID,
        seq=4,
        type=OutboxEventType.ANSWER_ACCEPTED,
    )

    envelope = outbox_event_to_envelope(event)

    assert envelope.type == "answer.accepted"
    assert envelope.seq == 4
    assert envelope.payload.total_score == 195
    assert quiz_channel(QUIZ_ID) == f"quiz:{QUIZ_ID}:events"
