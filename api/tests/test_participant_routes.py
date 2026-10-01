"""Tests for the public participant-join API contract."""

from uuid import UUID

from httpx import ASGITransport, AsyncClient

from quiz_api.application import get_app
from quiz_api.database.models import Participant, QuizStatus, RoundStatus
from quiz_api.security.tokens import TokenService
from quiz_api.services.participation import JoinResult
from quiz_api.services.snapshots import QuestionSnapshot, QuizSnapshot, RoundSnapshot
from quiz_api.web.api.quizzes.dependencies import (
    get_participation_service,
    get_quiz_snapshot_service,
    get_token_service,
)
from tests.test_application import build_test_settings

QUIZ_ID = UUID("10000000-0000-0000-0000-000000000001")
PARTICIPANT_ID = UUID("20000000-0000-0000-0000-000000000002")


class FakeParticipationService:
    """Return one durable participant without requiring a database in route tests."""

    async def join_quiz(self, **_: object) -> JoinResult:
        """Return the deterministic participant used by this route test."""
        return JoinResult(
            created=True,
            participant=Participant(
                display_name="Ada",
                id=PARTICIPANT_ID,
                join_key="request-1",
                quiz_id=QUIZ_ID,
                token_hash="a" * 64,
            ),
        )


class FakeQuizSnapshotService:
    """Return a client-safe active round without requiring a database in route tests."""

    async def get_snapshot(self, _: UUID) -> QuizSnapshot:
        """Return the deterministic active quiz used by this route test."""
        return QuizSnapshot(
            current_round=RoundSnapshot(
                closes_at=None,
                id=UUID("30000000-0000-0000-0000-000000000003"),
                opens_at=None,
                question=QuestionSnapshot(
                    options=("alleviate", "revoke"),
                    prompt="Which word means to make something less severe?",
                ),
                status=RoundStatus.OPEN,
            ),
            id=QUIZ_ID,
            status=QuizStatus.ACTIVE,
        )


def build_test_token_service() -> TokenService:
    """Create real signed tokens to verify the public response shape."""
    return TokenService(build_test_settings())


async def test_join_participant_returns_quiz_scoped_credentials() -> None:
    """A guest join returns command and stream credentials for the same quiz."""
    app = get_app(build_test_settings())
    app.dependency_overrides[get_participation_service] = FakeParticipationService
    app.dependency_overrides[get_token_service] = build_test_token_service
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/quizzes/{QUIZ_ID}/participants",
            headers={"Idempotency-Key": "request-1"},
            json={"display_name": "Ada"},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["participant_id"] == str(PARTICIPANT_ID)
    assert payload["quiz_id"] == str(QUIZ_ID)
    assert payload["participant_token"]
    assert payload["stream_url"].startswith(f"/v1/quizzes/{QUIZ_ID}/events?stream_token=")


async def test_quiz_snapshot_exposes_question_presentation_without_answer_key() -> None:
    """The quiz read endpoint does not return the server-only correct answer field."""
    app = get_app(build_test_settings())
    app.dependency_overrides[get_quiz_snapshot_service] = FakeQuizSnapshotService
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/v1/quizzes/{QUIZ_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "active"
    assert payload["current_round"]["question"] == {
        "options": ["alleviate", "revoke"],
        "prompt": "Which word means to make something less severe?",
    }
    assert "correct_answer" not in response.text
