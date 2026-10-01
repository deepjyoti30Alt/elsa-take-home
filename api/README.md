# Real-Time Vocabulary Quiz API

This directory contains the production-style FastAPI component for a live,
host-paced vocabulary quiz. PostgreSQL is the durable source of truth; local
Redis provides leaderboard projection and real-time event distribution.

The API is built incrementally according to the repository's local
implementation checklist. The project foundation is ready; the application,
migrations, and domain endpoints are added in subsequent phases.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop or another Docker-compatible runtime for local Redis
- A Neon PostgreSQL database (or another PostgreSQL-compatible database)

## Local setup

```bash
cd api
uv sync
cp .env.example .env
docker compose up -d redis
```

Edit `.env` before starting later API phases:

- Set `QUIZ_API_DATABASE_URL` to the Neon connection URL using the
  `postgresql+asyncpg` dialect.
- Replace `QUIZ_API_JWT_SIGNING_KEY` and `QUIZ_API_HOST_DEMO_TOKEN` with
  unique, long random values.
- Keep `QUIZ_API_REDIS_URL=redis://localhost:6379/0` when using the supplied
  Compose service.

Check the local Redis service:

```bash
docker compose ps
docker compose exec redis redis-cli ping
```

Stop Redis while preserving its local volume:

```bash
docker compose down
```

## Development commands

Run these commands from `api/`:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

The following commands are the stable interface planned for the next phases;
they will become executable when the corresponding application modules are
implemented:

```bash
# Apply the Alembic schema migrations.
uv run alembic upgrade head

# Create or refresh the deterministic vocabulary quiz used by the demo.
uv run python -m quiz_api.seed

# Run the API with automatic reload.
uv run uvicorn quiz_api.application:get_app --factory --reload
```

## Demo flow

Once all API phases are complete:

1. Apply migrations and run the seed command.
2. Start Redis and the API.
3. Join the seeded quiz from two or more clients using the participant endpoint.
4. Open a round with the host endpoint and `X-Host-Token`.
5. Submit answers and observe the SSE leaderboard stream update within the
   configured tick interval.
6. Close the round, then inspect the final standings and the generated OpenAPI
   documentation.

## Configuration reference

| Variable | Purpose |
| --- | --- |
| `QUIZ_API_DATABASE_URL` | Neon/PostgreSQL async SQLAlchemy URL. |
| `QUIZ_API_REDIS_URL` | Redis endpoint for leaderboard projection and pub/sub. |
| `QUIZ_API_JWT_SIGNING_KEY` | Secret used for participant and stream tokens. |
| `QUIZ_API_HOST_DEMO_TOKEN` | Secret required by host-only round controls. |
| `QUIZ_API_PARTICIPANT_TOKEN_TTL_SECONDS` | Participant-token lifetime. |
| `QUIZ_API_STREAM_TOKEN_TTL_SECONDS` | Short-lived SSE URL-token lifetime. |
| `QUIZ_API_LEADERBOARD_TICK_MS` | Coalescing interval for leaderboard broadcasts. |
| `QUIZ_API_FULL_LEADERBOARD_LIMIT` | Participant threshold for full stream payloads. |
| `QUIZ_API_COMPACT_LEADERBOARD_LIMIT` | Number of top entries in large-quiz stream payloads. |

Never commit `.env`, Neon credentials, signing keys, or host tokens.
