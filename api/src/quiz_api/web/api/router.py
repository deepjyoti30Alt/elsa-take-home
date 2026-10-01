"""Root router for the versioned quiz API."""

from typing import Final, Literal

from fastapi import APIRouter
from pydantic import BaseModel

API_PREFIX: Final[str] = "/v1"
PUBLIC_API_VERSION: Final[Literal["v1"]] = "v1"

api_router = APIRouter()


class ApiMetadataResponse(BaseModel):
    """Small discovery payload for the currently served API version."""

    api_version: Literal["v1"] = PUBLIC_API_VERSION
    service: Literal["real-time-vocabulary-quiz"] = "real-time-vocabulary-quiz"


@api_router.get("/", response_model=ApiMetadataResponse, tags=["api"])
async def get_api_metadata() -> ApiMetadataResponse:
    """Identify the currently served public API version."""
    return ApiMetadataResponse()
