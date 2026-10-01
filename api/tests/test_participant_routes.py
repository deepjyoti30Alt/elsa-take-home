"""Tests for the public participant-join API contract."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from quiz_api.application import get_app
from quiz_api.database.models import Participant, QuizStatus, RoundStatus
from quiz_api.security.tokens import TokenService
from quiz_api.services.answers import AnswerResult
from quiz_api.services.leaderboard import RankedStanding
from quiz_api.services.leaderboard_reads import LeaderboardPage
from quiz_api.services.participation import JoinResult
from quiz_api.services.quiz_reset import QuizResetResult
from quiz_api.services.rounds import AdvanceRoundResult, RoundTransitionResult
from quiz_api.services.snapshots import QuestionSnapshot, QuizSnapshot, RoundSnapshot
from quiz_api.web.api.quizzes.dependencies import (
    get_answer_service,
    get_authenticated_participant,
    get_leaderboard_read_service,
    get_participation_service,
    get_quiz_reset_service,
    get_quiz_snapshot_service,
    get_round_control_service,
    get_token_service,
)
from tests.test_application import build_test_settings

QUIZ_ID = UUID("10000000-0000-0000-0000-000000000001")
PARTICIPANT_ID = UUID("20000000-0000-0000-0000-000000000002")
ROUND_ID = UUID("30000000-0000-0000-0000-000000000003")
SUBMISSION_ID = UUID("40000000-0000-0000-0000-000000000004")


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


class FakeLeaderboardReadService:
    """Return a globally ranked page without requiring a database in route tests."""

    async def get_page(self, **_: object) -> LeaderboardPage:
        """Return a deterministic leaderboard page for the API contract test."""
        return LeaderboardPage(
            entries=(
                RankedStanding(
                    display_name="Ada",
                    participant_id=PARTICIPANT_ID,
                    rank=3,
                    total_response_ms=1200,
                    total_score=175,
                ),
            ),
            limit=50,
            offset=2,
            total=8,
        )


class FakeAnswerService:
    """Return a scored answer without requiring database infrastructure."""

    async def submit_answer(self, **_: object) -> AnswerResult:
        """Return the deterministic command result used by this route test."""
        return AnswerResult(
            awarded_points=95,
            is_correct=True,
            is_replay=False,
            response_ms=500,
            submission_id=SUBMISSION_ID,
            total_response_ms=500,
            total_score=95,
        )


class FakeRoundControlService:
    """Return host-controlled transitions without requiring database infrastructure."""

    async def open_round(self, **_: object) -> RoundTransitionResult:
        """Return the deterministic open transition used by this route test."""
        opens_at = datetime(2026, 10, 1, 12, tzinfo=UTC)
        return RoundTransitionResult(
            closes_at=opens_at + timedelta(seconds=30),
            opens_at=opens_at,
            round_id=ROUND_ID,
            status=RoundStatus.OPEN,
        )

    async def close_round(self, **_: object) -> RoundTransitionResult:
        """Return the deterministic close transition used by this route test."""
        opens_at = datetime(2026, 10, 1, 12, tzinfo=UTC)
        return RoundTransitionResult(
            closes_at=opens_at + timedelta(seconds=15),
            opens_at=opens_at,
            round_id=ROUND_ID,
            status=RoundStatus.CLOSED,
        )

    async def advance_round(self, **_: object) -> AdvanceRoundResult:
        """Return the next opened question after atomically closing the prior one."""
        opens_at = datetime(2026, 10, 1, 12, 0, 15, tzinfo=UTC)
        return AdvanceRoundResult(
            closed_round_id=ROUND_ID,
            completed=False,
            next_round=RoundTransitionResult(
                closes_at=opens_at + timedelta(seconds=30),
                opens_at=opens_at,
                round_id=UUID("30000000-0000-0000-0000-000000000005"),
                status=RoundStatus.OPEN,
            ),
        )


class FakeQuizResetService:
    """Return a reset confirmation without requiring a database or Redis."""

    async def reset_quiz(self, _: UUID) -> QuizResetResult:
        """Report the deterministic participant cleanup count used by route tests."""
        return QuizResetResult(removed_participants=2)


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


async def test_leaderboard_returns_paginated_deterministic_entries() -> None:
    """The endpoint returns global ranks alongside page and total metadata."""
    app = get_app(build_test_settings())
    app.dependency_overrides[get_leaderboard_read_service] = FakeLeaderboardReadService
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/v1/quizzes/{QUIZ_ID}/leaderboard?limit=50&offset=2")

    assert response.status_code == 200
    assert response.json() == {
        "entries": [
            {
                "display_name": "Ada",
                "participant_id": str(PARTICIPANT_ID),
                "rank": 3,
                "total_response_ms": 1200,
                "total_score": 175,
            },
        ],
        "limit": 50,
        "offset": 2,
        "total": 8,
    }


async def test_answer_submission_requires_authentication() -> None:
    """The answer command cannot run without a participant-scoped bearer token."""
    app = get_app(build_test_settings())
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/quizzes/{QUIZ_ID}/rounds/{ROUND_ID}/answers",
            json={"answer": "alleviate"},
        )

    assert response.status_code == 401


async def test_answer_submission_returns_authoritative_score() -> None:
    """An authenticated participant receives the command service's score result."""
    app = get_app(build_test_settings())
    app.dependency_overrides[get_answer_service] = FakeAnswerService
    app.dependency_overrides[get_authenticated_participant] = authenticated_participant
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/quizzes/{QUIZ_ID}/rounds/{ROUND_ID}/answers",
            json={"answer": "alleviate"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "awarded_points": 95,
        "is_correct": True,
        "is_replay": False,
        "response_ms": 500,
        "submission_id": str(SUBMISSION_ID),
        "total_response_ms": 500,
        "total_score": 95,
    }


async def test_open_round_requires_a_valid_host_token() -> None:
    """Host controls reject a request that omits the shared host credential."""
    app = get_app(build_test_settings())
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/quizzes/{QUIZ_ID}/rounds/{ROUND_ID}/open",
            json={"duration_seconds": 30},
        )

    assert response.status_code == 403


async def test_host_round_controls_return_authoritative_transitions() -> None:
    """A valid host token can open and close a configured quiz round."""
    app = get_app(build_test_settings())
    app.dependency_overrides[get_round_control_service] = FakeRoundControlService
    transport = ASGITransport(app=app)
    headers = {"X-Host-Token": "b" * 32}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        opened = await client.post(
            f"/v1/quizzes/{QUIZ_ID}/rounds/{ROUND_ID}/open",
            headers=headers,
            json={"duration_seconds": 30},
        )
        closed = await client.post(
            f"/v1/quizzes/{QUIZ_ID}/rounds/{ROUND_ID}/close",
            headers=headers,
        )

    assert opened.status_code == 200
    assert opened.json()["status"] == "open"
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"


async def test_host_can_advance_to_the_next_question() -> None:
    """The host shortcut returns the next open round without exposing answer content."""
    app = get_app(build_test_settings())
    app.dependency_overrides[get_round_control_service] = FakeRoundControlService
    transport = ASGITransport(app=app)
    headers = {"X-Host-Token": "b" * 32}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/quizzes/{QUIZ_ID}/rounds/advance",
            headers=headers,
            json={"duration_seconds": 30},
        )

    assert response.status_code == 200
    assert response.json()["closed_round_id"] == str(ROUND_ID)
    assert response.json()["next_round"]["status"] == "open"


async def test_host_can_reset_a_quiz_for_a_fresh_demo() -> None:
    """Reset is a host-only operation that returns the number of removed participants."""
    app = get_app(build_test_settings())
    app.dependency_overrides[get_quiz_reset_service] = FakeQuizResetService
    transport = ASGITransport(app=app)
    headers = {"X-Host-Token": "b" * 32}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(f"/v1/quizzes/{QUIZ_ID}/reset", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"removed_participants": 2, "status": "draft"}


async def test_event_stream_rejects_an_invalid_query_token_before_connecting() -> None:
    """Native EventSource credentials are short-lived stream tokens, never bearer tokens."""
    app = get_app(build_test_settings())
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/v1/quizzes/{QUIZ_ID}/events?stream_token=invalid")

    assert response.status_code == 401


def authenticated_participant() -> object:
    """Provide valid participant claims without coupling the route test to headers."""
    token_service = build_test_token_service()
    participant = Participant(
        display_name="Ada",
        id=PARTICIPANT_ID,
        join_key="request-1",
        quiz_id=QUIZ_ID,
        token_hash="a" * 64,
    )
    token = token_service.issue_participant_token(participant)
    return token_service.validate_participant_token(token, quiz_id=QUIZ_ID)
