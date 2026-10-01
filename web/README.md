# Vocabulary Live web client

This Bun-managed React application is the demo client for the FastAPI quiz
API. It has separate **Play quiz** and **Host quiz** workspaces: player REST
commands join and submit answers while a native browser `EventSource` receives
live snapshot, round, and leaderboard events. The host starts the first
question, advances all players through the next four questions, and can reset a
disposable demo. The leaderboard remains public in both views.

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
   of `QUIZ_API_HOST_DEMO_TOKEN`, then select **Log in as host**. Do not start
   the first question yet.
2. Open `http://127.0.0.1:5173` in two more browser windows (incognito windows
   are useful). In each, stay on **Play quiz**, enter the seeded quiz ID and a
   distinct display name, then select **Join quiz**.
3. Back in the Host workspace, choose a duration (120 seconds is the default)
   and select **Start first question**. New player joins are intentionally
   disabled once this happens.
4. Observe the answer result and the coalesced live leaderboard update. It is
   visible to the host and players; the current player is highlighted in blue.
5. Select **Next question** to close the current question and immediately move
   every player to the next one. Repeat for all five questions. The fifth
   advance completes the quiz.
6. Select **Reset quiz for another test** to restore all five questions and
   remove scores and participants. Reload player windows and join again.

Browser developer tools should show a single persistent
`/api/v1/quizzes/.../events` request for every joined player window;
disconnecting and reconnecting receives a new `quiz.snapshot`.

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
