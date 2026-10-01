"""Versioned event contracts shared by projection and delivery workers."""

from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from quiz_api.database.models import OutboxEvent, OutboxEventType, QuizStatus, RoundStatus
from quiz_api.services.snapshots import QuizSnapshot

EVENT_SCHEMA_VERSION: Final[Literal[1]] = 1


class AnswerAcceptedEventPayload(BaseModel):
    """Durable score totals emitted after one answer transaction commits."""

    display_name: str
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


class SnapshotQuestionEventPayload(BaseModel):
    """Presentation-safe question content carried by the first SSE event."""

    options: tuple[str, ...]
    prompt: str


class SnapshotRoundEventPayload(BaseModel):
    """Current round state carried by a stream snapshot."""

    closes_at: datetime | None
    id: UUID
    opens_at: datetime | None
    question: SnapshotQuestionEventPayload
    status: RoundStatus


class QuizSnapshotEventPayload(BaseModel):
    """Full client-safe quiz state sent first on every stream connection."""

    current_round: SnapshotRoundEventPayload | None
    event_version: Literal[1] = EVENT_SCHEMA_VERSION
    quiz_id: UUID
    seq: int = Field(ge=0)
    status: QuizStatus


def quiz_snapshot_event_payload(snapshot: QuizSnapshot) -> QuizSnapshotEventPayload:
    """Convert a database-backed quiz snapshot into the first SSE event payload."""
    current_round = None
    if snapshot.current_round is not None:
        current_round = SnapshotRoundEventPayload(
            closes_at=snapshot.current_round.closes_at,
            id=snapshot.current_round.id,
            opens_at=snapshot.current_round.opens_at,
            question=SnapshotQuestionEventPayload(
                options=snapshot.current_round.question.options,
                prompt=snapshot.current_round.question.prompt,
            ),
            status=snapshot.current_round.status,
        )
    return QuizSnapshotEventPayload(
        current_round=current_round,
        quiz_id=snapshot.id,
        seq=snapshot.event_seq,
        status=snapshot.status,
    )


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
