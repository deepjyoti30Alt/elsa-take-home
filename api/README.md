# Real-Time Vocabulary Quiz API

This directory contains the FastAPI component for a host-paced, live
vocabulary quiz. PostgreSQL is the durable source of truth for quiz state,
answers, scores, and the transactional outbox. Redis holds a rebuildable
leaderboard projection and distributes round and coalesced leaderboard events.

The current API supports joining a quiz, reading its public state and
leaderboard, submitting an answer, and host-controlled round transitions.
Interactive OpenAPI documentation is available at `/docs` when the service is
running.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop or another Docker-compatible runtime for local Redis
- A Neon PostgreSQL database, or another PostgreSQL-compatible database

## Local setup

Run from this directory:

```bash
uv sync
cp .env.example .env
docker compose up -d redis
```

Edit `.env` before starting the API:

- Set `QUIZ_API_DATABASE_URL` to the Neon URL rewritten to use the
  `postgresql+asyncpg` dialect.
- Replace `QUIZ_API_JWT_SIGNING_KEY` and `QUIZ_API_HOST_DEMO_TOKEN` with
  separate random secrets of at least 32 characters.
- Keep `QUIZ_API_REDIS_URL=redis://localhost:6379/0` when using the supplied
  Compose service.

Prepare deterministic demo data and start the server:

```bash
uv run alembic upgrade head
uv run python -m quiz_api.seed
uv run uvicorn quiz_api.application:get_app --factory --reload
```

The seeded quiz ID is `10000000-0000-0000-0000-000000000001`. The seed is
idempotent and creates five pending one-question rounds. Participants must join
before the host starts the first round; new joins are locked once the quiz is
active.

Check or stop the local Redis service with:

```bash
docker compose ps
docker compose exec redis redis-cli ping
docker compose down
```

## API contract

All application endpoints are versioned under `/v1`. UUID path values below
are represented as `{quiz_id}` and `{round_id}`. Every error uses this shape:

```json
{
  "error": {
    "code": "conflict",
    "correlation_id": "request-id",
    "message": "The requested operation conflicts with quiz state."
  }
}
```

| Method and path | Purpose | Credentials |
| --- | --- | --- |
| `POST /v1/quizzes/{quiz_id}/participants` | Join a draft quiz and receive quiz-scoped participant and stream tokens. | None; optional `Idempotency-Key`; existing keys can reconnect after start. |
| `GET /v1/quizzes/{quiz_id}` | Read public quiz state and the active question, never its answer key. | None. |
| `GET /v1/quizzes/{quiz_id}/leaderboard?limit=50&offset=0` | Read a globally ranked, paginated leaderboard. | None. |
| `POST /v1/quizzes/{quiz_id}/rounds/{round_id}/answers` | Submit an answer, or safely replay the prior identical submission. | `Authorization: Bearer <participant-token>`. |
| `POST /v1/quizzes/{quiz_id}/rounds/{round_id}/open` | Open a pending round for a bounded duration. | `X-Host-Token`. |
| `POST /v1/quizzes/{quiz_id}/rounds/{round_id}/close` | Close the currently open round. | `X-Host-Token`. |
| `POST /v1/quizzes/{quiz_id}/rounds/advance` | Close the current question and open the next pending question. | `X-Host-Token`. |
| `POST /v1/quizzes/{quiz_id}/reset` | Clear runtime data and restore all five rounds for a new demo. | `X-Host-Token`. |
| `GET /v1/quizzes/{quiz_id}/events?stream_token=...` | Receive a snapshot and live SSE updates. | Quiz-scoped stream token in the query string. |
| `GET /health` | Liveness probe for the API process. | None. |
| `GET /ready` | Readiness probe that checks PostgreSQL and Redis. | None. |

`POST /answers` returns the authoritative correctness, awarded points,
response time, cumulative score, and `is_replay`. The database clock, rather
than a client timestamp, decides whether a round is accepting answers.

### Demo sequence

Set the deterministic identifiers used by the seed:

```bash
export QUIZ_ID=10000000-0000-0000-0000-000000000001
export ROUND_ID=30000000-0000-0000-0000-000000000001
```

Join as a participant. Preserve the returned `participant_token` privately;
the stream token is short-lived and scoped only to the SSE connection.

```bash
curl -X POST "http://127.0.0.1:8000/v1/quizzes/${QUIZ_ID}/participants" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-ada' \
  -d '{"display_name":"Ada"}'
```

After every participant has joined, open the first round using the value
configured in `QUIZ_API_HOST_DEMO_TOKEN`:

```bash
curl -X POST "http://127.0.0.1:8000/v1/quizzes/${QUIZ_ID}/rounds/${ROUND_ID}/open" \
  -H "X-Host-Token: ${QUIZ_API_HOST_DEMO_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"duration_seconds":120}'
```

Then submit an answer with the participant token from the join response:

```bash
curl -X POST "http://127.0.0.1:8000/v1/quizzes/${QUIZ_ID}/rounds/${ROUND_ID}/answers" \
  -H "Authorization: Bearer ${PARTICIPANT_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"answer":"alleviate"}'
```

Inspect the current standings with:

```bash
curl "http://127.0.0.1:8000/v1/quizzes/${QUIZ_ID}/leaderboard?limit=50&offset=0"
```

Move every connected player to the next question with one host action:

```bash
curl -X POST "http://127.0.0.1:8000/v1/quizzes/${QUIZ_ID}/rounds/advance" \
  -H "X-Host-Token: ${QUIZ_API_HOST_DEMO_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"duration_seconds":120}'
```

After the fifth question, or at any point during a disposable demo, reset all
participants, answers, scores, outbox events, and cached standings. Existing
players must reload and join again after a reset:

```bash
curl -X POST "http://127.0.0.1:8000/v1/quizzes/${QUIZ_ID}/reset" \
  -H "X-Host-Token: ${QUIZ_API_HOST_DEMO_TOKEN}"
```

## Server-Sent Events

The join response contains a `stream_url` such as
`/v1/quizzes/{quiz_id}/events?stream_token=...`. Use it directly with the
browser's native `EventSource`; native EventSource does not support an
`Authorization` header. A participant command token cannot open a stream, and
a stream token cannot submit an answer.

```js
const stream = new EventSource(`http://127.0.0.1:8000${joinResponse.stream_url}`)

stream.addEventListener("quiz.snapshot", (message) => {
  const snapshot = JSON.parse(message.data)
  // Replace local quiz state and retain snapshot.seq.
})

stream.addEventListener("round.opened", applyEvent)
stream.addEventListener("round.closed", applyEvent)
stream.addEventListener("leaderboard.updated", applyEvent)
```

Every connection and reconnection receives `quiz.snapshot` first. Subsequent
events have an `id` and a versioned JSON body with the durable per-quiz `seq`.
Clients should ignore an event whose sequence is not newer than the state they
hold. The server emits comment heartbeats at
`QUIZ_API_SSE_HEARTBEAT_SECONDS`, keeping load balancers and idle browser
connections alive.

Each API process creates a Redis pub/sub subscription for a quiz only while it
has at least one local SSE listener. On disconnect and shutdown it cancels the
listener, wakes any waiting stream generators, and closes the Redis pub/sub
connection. Clients reconnect to receive a fresh snapshot. A transient
subscription failure reconnects while local listeners remain. Per-listener
queues are bounded; a slow client drops its oldest queued event and converges
again from a fresh snapshot on reconnect.

## Projection and delivery workers

The API starts an outbox relay and leaderboard ticker with its lifespan. The
command handlers never write Redis directly. After an answer transaction
commits, the relay writes the participant's absolute totals to the quiz Redis
sorted set and sidecar hashes. Repeating that write after a worker failure is
safe because it overwrites totals rather than incrementing them.

The relay publishes `round.opened` and `round.closed` to the quiz Redis
channel. The ticker coalesces accepted answers per quiz and publishes no more
than one `leaderboard.updated` event during each configured 250–500 ms tick.
All delivery events have a schema version and the durable per-quiz sequence of
the state change that produced them.

If Redis is unavailable, incomplete, or malformed, the REST leaderboard
transparently reads the same deterministic page from PostgreSQL. Redis can be
reconstructed at any time from participant totals:

```bash
uv run python -m quiz_api.rebuild_projection "${QUIZ_ID}"
```

The outbox relay leaves a failed event unpublished and retries with bounded
exponential backoff. For a production multi-instance deployment, run relay and
ticker workers under one elected-worker or distributed-lock arrangement so
each outbox row is projected once at a time; duplicate delivery remains safe.

## Operations and observability

`/health` reports only that the API process can serve requests. `/ready` checks
PostgreSQL and Redis concurrently, returning HTTP 200 only when both are
available. Its JSON response reports each dependency separately; it returns
HTTP 503 when either is unavailable. Use `/ready` for deployment traffic
routing and `/health` for process liveness.

`/metrics` is a Prometheus text-format scrape endpoint. It records HTTP request
counts and latency, answer outcomes, outbox lag and failures, leaderboard-tick
duration, event fan-out delay, active SSE streams, reconnects, and database or
Redis readiness failures. The request middleware also creates OpenTelemetry
request spans. The application deliberately does not configure an exporter;
production deployment supplies the OpenTelemetry provider/exporter and protects
the metrics endpoint at the network layer.

Shutdown stops the relay and ticker workers, cancels pub/sub listeners, and
wakes live SSE generators so connections close cleanly. Durable state remains
in PostgreSQL, and a reconnect receives the authoritative snapshot.

### Load scenarios

`load_tests/quiz_burst.py` contains two Locust user types: a one-answer user
for a five-second answer burst and a user that holds an SSE connection for one
minute. Seed the API and open the configured round before running it. From
`api/`, use a five-second spawn window, for example:

```bash
QUIZ_ID=10000000-0000-0000-0000-000000000001 \
ROUND_ID=30000000-0000-0000-0000-000000000001 \
uv run locust -f load_tests/quiz_burst.py --host http://127.0.0.1:8000
```

In the Locust UI, select the desired mix of answer-burst and sustained-SSE
users, then spawn the target total over five seconds. Record the
`quiz_api_event_delivery_delay_seconds` histogram alongside Locust request
latency to assess the 500 ms answer-to-broadcast objective.

## Security and delivery behavior

- Participant tokens are signed JWTs scoped to one quiz and cannot authorize
  stream connections; stream tokens cannot authorize answer commands.
- Host controls compare `X-Host-Token` using a constant-time comparison.
- Input schemas bound display names, answers, duration, and pagination.
- Expected domain failures map to safe 404, 409, or 422 responses; unexpected
  exceptions do not expose internal details.
- New joins are accepted only while a quiz is in draft. A retry with the same
  idempotency key can recover its existing participant credentials after the
  quiz begins. Join attempts are limited per peer address. Answer attempts are limited per
  participant and peer address. The demo limiter is process-local; a
  multi-instance deployment must replace it with an atomic Redis limit.
- Each response includes `X-Request-ID`, which is also included in error
  bodies for support correlation.

## Configuration reference

| Variable | Purpose |
| --- | --- |
| `QUIZ_API_DATABASE_URL` | Neon/PostgreSQL async SQLAlchemy URL. |
| `QUIZ_API_REDIS_URL` | Redis endpoint for leaderboard projection and pub/sub. |
| `QUIZ_API_JWT_SIGNING_KEY` | Secret used for participant and stream tokens. |
| `QUIZ_API_HOST_DEMO_TOKEN` | Secret required by host-only round controls. |
| `QUIZ_API_PARTICIPANT_TOKEN_TTL_SECONDS` | Participant-token lifetime. |
| `QUIZ_API_STREAM_TOKEN_TTL_SECONDS` | Short-lived stream-token lifetime. |
| `QUIZ_API_JOIN_RATE_LIMIT_PER_MINUTE` | Per-address participant-join allowance. |
| `QUIZ_API_ANSWER_RATE_LIMIT_PER_MINUTE` | Per participant/address answer allowance. |
| `QUIZ_API_OUTBOX_RELAY_BATCH_SIZE` | Maximum unpublished events handled in one relay transaction. |
| `QUIZ_API_OUTBOX_RELAY_POLL_MS` | Idle delay before polling for unpublished events. |
| `QUIZ_API_OUTBOX_RELAY_RETRY_MAX_SECONDS` | Maximum relay backoff after a failed projection/delivery. |
| `QUIZ_API_SSE_HEARTBEAT_SECONDS` | Interval for SSE comment heartbeats. |
| `QUIZ_API_SSE_QUEUE_SIZE` | Maximum buffered events for one local SSE connection. |
| `QUIZ_API_LEADERBOARD_TICK_MS` | Coalescing interval for leaderboard broadcasts. |
| `QUIZ_API_FULL_LEADERBOARD_LIMIT` | Participant threshold for full leaderboard event payloads. |
| `QUIZ_API_COMPACT_LEADERBOARD_LIMIT` | Top-entry count in large leaderboard event payloads. |

Never commit `.env`, Neon credentials, signing keys, participant tokens, or
host tokens.

## Quality checks

Run these commands from `api/` before submitting changes:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

The suite includes API-level readiness and metrics checks, SSE lifecycle tests,
leaderboard concurrency and retry-recovery tests, plus the Locust scenario for
manual capacity testing.
