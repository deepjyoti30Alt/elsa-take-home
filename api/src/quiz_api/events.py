"""Versioned event contracts shared by projection and delivery workers."""

from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from quiz_api.database.models import OutboxEvent, OutboxEventType, RoundStatus

EVENT_SCHEMA_VERSION: Final[Literal[1]] = 1


class AnswerAcceptedEventPayload(BaseModel):
    """Durable score totals emitted after one answer transaction commits."""

    event_version: Literal[1]
    is_correct: bool
    participant_id: UUID
    response_ms: int = Field(ge=0)
    total_response_ms: int = Field(ge=0)
    total_score: int = Field(ge=0)


class RoundEventPayload(BaseModel):
    """Durable timing state emitted after a host opens or closes a round."""

    closes_at: datetime
    event_version: Literal[1]
    opens_at: datetime
    round_id: UUID
    status: RoundStatus


class LeaderboardStandingEventPayload(BaseModel):
    """One leaderboard standing carried by a coalesced update event."""

    display_name: str
    participant_id: UUID
    rank: int = Field(ge=1)
    total_response_ms: int = Field(ge=0)
    total_score: int = Field(ge=0)


class LeaderboardUpdatedEventPayload(BaseModel):
    """Bounded standings projection emitted once per changed quiz per tick."""

    event_version: Literal[1]
    standings: tuple[LeaderboardStandingEventPayload, ...]
    total_participants: int = Field(ge=0)


class QuizEventEnvelope(BaseModel):
    """Wire-safe, ordered event delivered to quiz-specific Redis channels."""

    event_version: Literal[1] = EVENT_SCHEMA_VERSION
    occurred_at: datetime
    payload: AnswerAcceptedEventPayload | RoundEventPayload | LeaderboardUpdatedEventPayload
    quiz_id: UUID
    seq: int = Field(ge=1)
    type: Literal["answer.accepted", "round.opened", "round.closed", "leaderboard.updated"]


RoundPayloadAdapter = TypeAdapter(RoundEventPayload)
AnswerPayloadAdapter = TypeAdapter(AnswerAcceptedEventPayload)


def outbox_event_to_envelope(event: OutboxEvent) -> QuizEventEnvelope:
    """Validate one durable event and convert it to its delivery contract."""
    event_type = event.type
    payload: AnswerAcceptedEventPayload | RoundEventPayload
    wire_type: Literal["answer.accepted", "round.opened", "round.closed"]
    if event_type is OutboxEventType.ANSWER_ACCEPTED:
        payload = AnswerPayloadAdapter.validate_python(event.payload)
        wire_type = "answer.accepted"
    elif event_type is OutboxEventType.ROUND_OPENED:
        payload = RoundPayloadAdapter.validate_python(event.payload)
        wire_type = "round.opened"
    elif event_type is OutboxEventType.ROUND_CLOSED:
        payload = RoundPayloadAdapter.validate_python(event.payload)
        wire_type = "round.closed"
    else:
        message = f"Unsupported outbox event type: {event_type}"
        raise ValueError(message)
    return QuizEventEnvelope(
        occurred_at=event.created_at,
        payload=payload,
        quiz_id=event.quiz_id,
        seq=event.seq,
        type=wire_type,
    )


def quiz_channel(quiz_id: UUID) -> str:
    """Return the Redis pub/sub channel reserved for one quiz's events."""
    return f"quiz:{quiz_id}:events"
