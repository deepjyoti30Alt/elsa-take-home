"""Pydantic contracts for quiz participation and state endpoints."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
