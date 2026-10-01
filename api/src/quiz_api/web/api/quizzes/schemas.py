"""Pydantic contracts for quiz participation and state endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from quiz_api.database.models import QuizStatus, RoundStatus


class JoinParticipantRequest(BaseModel):
    """Guest-provided data required to enter a quiz."""

    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=80)


class JoinParticipantResponse(BaseModel):
    """Quiz-scoped credentials and stream location returned after a guest joins."""

    participant_id: UUID
    participant_token: str
    quiz_id: UUID
    stream_url: str


class QuestionSnapshotResponse(BaseModel):
    """Presentation-safe active-question content for a quiz snapshot."""

    options: tuple[str, ...]
    prompt: str


class RoundSnapshotResponse(BaseModel):
    """Current shared-round state delivered to a quiz client."""

    closes_at: datetime | None
    id: UUID
    opens_at: datetime | None
    question: QuestionSnapshotResponse
    status: RoundStatus


class QuizSnapshotResponse(BaseModel):
    """Client-visible quiz lifecycle state and optional current round."""

    current_round: RoundSnapshotResponse | None
    id: UUID
    status: QuizStatus


class LeaderboardEntryResponse(BaseModel):
    """One participant's deterministic place in the quiz leaderboard."""

    display_name: str
    participant_id: UUID
    rank: int
    total_response_ms: int
    total_score: int


class LeaderboardPageResponse(BaseModel):
    """Paginated quiz leaderboard response."""

    entries: tuple[LeaderboardEntryResponse, ...]
    limit: int
    offset: int
    total: int


class SubmitAnswerRequest(BaseModel):
    """Participant-provided answer for one opened quiz round."""

    model_config = ConfigDict(str_strip_whitespace=True)

    answer: str = Field(min_length=1, max_length=255)


class SubmitAnswerResponse(BaseModel):
    """Authoritative result of accepting or replaying a round answer."""

    awarded_points: int
    is_correct: bool
    is_replay: bool
    response_ms: int
    submission_id: UUID
    total_response_ms: int
    total_score: int
