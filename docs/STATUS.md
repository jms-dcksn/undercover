# Status

The pilot is implemented and verified locally. Supabase initialization and hosted access checks are pending the development connection and project confirmation.

The dashboard includes a searchable/filterable queue, full claim evidence, customer history, policy/plan terms, live activity, read-only instructions and handler sign-off/payment controls. It follows the brand and adapts to mobile widths.

The agent fetches its instructions and records through FastAPI and records real tool activity. The API runs it in the background, prevents duplicate starts and preserves committed decisions/payments on failure. The model defaults to `openai/gpt-6-luna` with low reasoning effort unless `MODEL_NAME` is set.

## Setup

Install dependencies with `uv sync` and `npm install`. Copy the placeholders in `.env.example` into your ignored `.env` and supply the connection strings:

- `DATABASE_URL`: dedicated development Supabase Postgres connection, preferably the session pooler on IPv4 networks. Include `sslmode=require` for hosted connections.
- `TEST_DATABASE_URL`: separate disposable Postgres database; use the local helper below or provide your own. Tests delete application records in this database.
- `OPENROUTER_API_KEY`: needed for real agent runs, never for tests.
- `MODEL_NAME`: optional OpenRouter model override.
- `BACKEND_URL`: defaults to `http://127.0.0.1:8000`.

After confirming the development target, run:

```text
uv run -m backend.manage init
uv run -m backend.manage seed
npm run dev
```

Initialization creates only the private `undercover` schema and its tables. Seeding adds the 25 queue claims and reference data without overwriting existing state. No evaluation or manual files are loaded.

Open `http://localhost:5173`; the backend runs on port 8000. Select a waiting claim and choose **Run claim**. An approval above $1,000 waits for handler sign-off; then choose **Simulate payment**. No real payment is made.

## Tests

For a temporary local Postgres with no system service or Docker, run:

```text
uv run -m e2e.local
```

Copy the printed `TEST_DATABASE_URL` line into `.env`, replacing any previous value. Keep that terminal open and run `npm run check` in another terminal. Press Enter in the helper terminal to stop and delete the test database; update the URL each time you start a new one.

For an existing, separate disposable Postgres, set `TEST_DATABASE_URL` and run `uv run -m backend.manage init-test` before the checks. First initialization requires an empty application schema; it refuses to relabel an existing application database as disposable. Direct and pooled Supabase connections to the same project/database are treated as the same target.

`npm run check` runs all checks; `npm run check:python` and `npm run check:ts` run the unit checks separately. Playwright uses ports 8010 and 5174, a marked test database and a delayed scripted model. It never reuses the development servers or calls OpenRouter.

## Verification

- Local Postgres: 25 seeded waiting claims, three plans and three handlers. Repeat seeding preserves decisions/payments, and saved state survives a backend restart. Private application tables have RLS enabled.
- Python: 48 tests pass with 99.57% coverage. Formatting, lint and types pass. Tests cover payment boundaries/concurrency, scoped tools, time/iteration limits, failures after committed actions, database isolation and safe setup errors.
- Dashboard: 13 tests pass with over 99% statement coverage. Playwright MCP checks confirm the 25-claim desk, full documents/history, read-only instructions, keyboard focus and desktop/mobile layouts with no horizontal overflow or application console errors.
- Playwright: eight end-to-end scenarios cover approve/decline/refer, live work, duplicate starts, the exact $1,000 boundary, blocked agent payment, handler sign-off, simulated payment, failure display and refresh persistence. MCP also verifies the sign-off flow and saved payment after a backend restart.
- Production dashboard build and frontend secret scan pass. No live model calls were made, and model decision accuracy has not been evaluated.
- Supabase development initialization, seeding and Data API/role access checks remain unverified. No Supabase project has been modified.

## Pilot limits

Run one backend process. Business records persist in Postgres, but agent execution is not durable: stopping the backend during a run can leave a claim in progress and requires inspection before manual recovery. Completed decisions are immutable, and failed runs preserve committed decisions/payments. There is no sign-in, real payment or customer messaging.
