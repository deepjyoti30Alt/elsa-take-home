"""Locust scenarios for a five-second answer burst and sustained SSE streams.

Run after seeding and host-opening a round:
    QUIZ_ID=... ROUND_ID=... locust -f load_tests/quiz_burst.py --host http://127.0.0.1:8000
"""

import os
from uuid import uuid4

import gevent
from locust import HttpUser, between, task
from locust.exception import StopUser

QUIZ_ID = os.environ.get("QUIZ_ID", "10000000-0000-0000-0000-000000000001")
ROUND_ID = os.environ.get("ROUND_ID", "30000000-0000-0000-0000-000000000001")
ANSWER = os.environ.get("QUIZ_ANSWER", "alleviate")


class JoinedQuizUser(HttpUser):
    """Base Locust user that enters the configured quiz as a unique guest."""

    abstract = True
    wait_time = between(0.01, 0.05)

    def on_start(self) -> None:
        """Join once and retain the command and stream credentials for this virtual user."""
        response = self.client.post(
            f"/v1/quizzes/{QUIZ_ID}/participants",
            headers={"Idempotency-Key": str(uuid4())},
            json={"display_name": f"load-{uuid4().hex[:8]}"},
            name="join_quiz",
        )
        response.raise_for_status()
        payload = response.json()
        self.participant_token = payload["participant_token"]
        self.stream_url = payload["stream_url"]


class QuizAnswerBurstUser(JoinedQuizUser):
    """Submit exactly one answer; use a five-second spawn window to model a round burst."""

    @task
    def submit_answer(self) -> None:
        """Send one authenticated answer then stop this virtual user."""
        self.client.post(
            f"/v1/quizzes/{QUIZ_ID}/rounds/{ROUND_ID}/answers",
            headers={"Authorization": f"Bearer {self.participant_token}"},
            json={"answer": ANSWER},
            name="submit_answer",
        )
        raise StopUser


class SustainedSseUser(JoinedQuizUser):
    """Hold a native-style HTTP SSE connection open for one minute per virtual user."""

    @task
    def hold_stream(self) -> None:
        """Open the stream and keep its socket occupied to exercise connection capacity."""
        with self.client.get(self.stream_url, stream=True, name="sse_stream") as response:
            if response.status_code != 200:
                response.failure(f"Unexpected SSE status: {response.status_code}")
                raise StopUser
            gevent.sleep(60)
        raise StopUser
