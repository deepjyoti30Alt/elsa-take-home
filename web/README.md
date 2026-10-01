# Vocabulary Live web client

This Bun-managed React application is the demo client for the FastAPI quiz
API. It has separate **Play quiz** and **Host quiz** workspaces: player REST
commands join and submit answers while a native browser `EventSource` receives
live snapshot, round, and leaderboard events. Host controls open and close
rounds. The leaderboard remains public in both views.

## Local setup

Use Node 22 through NVM for Bun dependency hooks, then run these commands from
this directory:

```bash
nvm use 22
cp .env.example .env
bun install
bun run dev
```

The app is served at `http://127.0.0.1:5173`. Its default `/api` base is a Vite
development proxy to `http://127.0.0.1:8000`, so both REST calls and the
long-lived EventSource stream use the same browser origin. Do not use the
FastAPI API address directly during local development.

`VITE_API_PROXY_TARGET` changes the API target for Vite. Keep
`VITE_API_BASE_URL=/api` unless a deployment serves the API through the same
origin and path.

## End-to-end demo

First prepare the API in a separate terminal:

```bash
cd ../api
uv sync
docker compose up -d redis
uv run alembic upgrade head
uv run python -m quiz_api.seed
uv run uvicorn quiz_api.application:get_app --factory --reload
```

Ensure `api/.env` has valid Neon credentials, Redis settings, and a
`QUIZ_API_HOST_DEMO_TOKEN`. Then run the web client as described above.

1. In one window, select **Host quiz**, enter the seeded quiz ID and the value
   of `QUIZ_API_HOST_DEMO_TOKEN`, then select **Log in as host**. The initial
   seeded round ID is already populated:
   `30000000-0000-0000-0000-000000000001`. Choose a duration and select
   **Open round**.
2. Open `http://127.0.0.1:5173` in two more browser windows (incognito windows
   are useful). In each, stay on **Play quiz**, enter the seeded quiz ID and a
   distinct display name, then select **Join quiz**.
3. The player windows receive `round.opened` through SSE and show the question
   and shared countdown. Submit an option from each player window.
4. Observe the answer result and the coalesced live leaderboard update. It is
   visible to the host and players; the current player is highlighted in blue.
5. In the Host workspace, select **Close current round**. The host refreshes
   public state every second; player views receive the `round.closed` event.

The other seeded round IDs end in `...0002` and `...0003`. Put the next ID into
the host round field before opening it. Browser developer tools should show a
single persistent `/api/v1/quizzes/.../events` request for every joined
window; disconnecting and reconnecting receives a new `quiz.snapshot`.

## Verification

```bash
nvm use 22
bun run typecheck
bun run build
```

The application keeps participant and stream tokens only in component memory;
refreshing the page intentionally requires a new participant join. Host tokens
are likewise never persisted. Switching workspace intentionally clears the
previous role's credentials and stream so host and player sessions do not mix.
