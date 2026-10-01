"""Prometheus metrics and OpenTelemetry hooks for quiz runtime operations."""

from datetime import UTC, datetime

from opentelemetry import trace
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()
tracer = trace.get_tracer("quiz_api")

REQUEST_COUNT = Counter(
    "quiz_api_requests_total",
    "Completed HTTP requests by method, route, and status.",
    ("method", "path", "status"),
    registry=REGISTRY,
)
REQUEST_DURATION = Histogram(
    "quiz_api_request_duration_seconds",
    "Completed HTTP request latency.",
    ("method", "path"),
    registry=REGISTRY,
)
ANSWER_COUNT = Counter(
    "quiz_api_answers_total",
    "Accepted answer outcomes, including idempotent replays.",
    ("correct", "replay"),
    registry=REGISTRY,
)
OUTBOX_LAG = Gauge(
    "quiz_api_outbox_oldest_unpublished_seconds",
    "Age of the oldest event handled by the relay batch.",
    registry=REGISTRY,
)
OUTBOX_FAILURES = Counter(
    "quiz_api_outbox_failures_total",
    "Outbox relay delivery failures.",
    registry=REGISTRY,
)
TICK_DURATION = Histogram(
    "quiz_api_leaderboard_tick_duration_seconds",
    "Leaderboard ticker execution duration.",
    registry=REGISTRY,
)
EVENT_DELIVERY_DELAY = Histogram(
    "quiz_api_event_delivery_delay_seconds",
    "Delay between a durable event timestamp and local stream fan-out.",
    registry=REGISTRY,
)
ACTIVE_STREAMS = Gauge(
    "quiz_api_active_streams",
    "Local active SSE connections.",
    registry=REGISTRY,
)
STREAM_RECONNECTS = Counter(
    "quiz_api_stream_reconnects_total",
    "Redis pub/sub listener reconnections after transient failures.",
    registry=REGISTRY,
)
DEPENDENCY_FAILURES = Counter(
    "quiz_api_dependency_failures_total",
    "Database, Redis, and worker dependency failures.",
    ("dependency",),
    registry=REGISTRY,
)


def metrics_payload() -> bytes:
    """Serialize this service's Prometheus registry for the scrape endpoint."""
    return generate_latest(REGISTRY)


def record_answer(*, is_correct: bool, is_replay: bool) -> None:
    """Count an accepted answer outcome without recording participant identity."""
    ANSWER_COUNT.labels(correct=str(is_correct).lower(), replay=str(is_replay).lower()).inc()


def record_event_delivery_delay(occurred_at: datetime) -> None:
    """Observe local fan-out delay for a durable event timestamp."""
    delay = max((datetime.now(UTC) - occurred_at).total_seconds(), 0)
    EVENT_DELIVERY_DELAY.observe(delay)


def record_outbox_lag(created_at: datetime) -> None:
    """Set current relay lag based on one event's durable creation timestamp."""
    OUTBOX_LAG.set(max((datetime.now(UTC) - created_at).total_seconds(), 0))
