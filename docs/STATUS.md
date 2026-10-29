# Status

The pilot uses local Postgres for development and tests. The database launcher creates and seeds development storage, prepares an isolated test database and saves the local connections in `.env`.

The dashboard includes a searchable/filterable queue, full claim evidence, customer history, policy/plan terms, live activity, read-only instructions and handler sign-off/payment controls. It follows the brand and adapts to mobile widths.

The agent fetches its instructions and records through FastAPI and records real tool activity. The API runs it in the background, prevents duplicate starts and preserves committed decisions/payments on failure. The model defaults to `openai/gpt-6-luna` with low reasoning effort unless `MODEL_NAME` is set.

## Setup

Install dependencies and start the database in one terminal:

```text
uv sync
npm install
uv run -m backend.local
```

Keep it running, then start the app in another terminal:

```text
npm run dev
```

The launcher creates `undercover` and `undercover_test`, seeds 25 development claims and updates only the two database settings in the ignored `.env`. Existing API keys and model settings are preserved. It uses a local socket on macOS/Linux and loopback TCP on Windows. Backend connections reject remote hosts.

Configuration:

- `DATABASE_URL`: generated local development connection to `undercover`.
- `TEST_DATABASE_URL`: generated local connection to `undercover_test`. Tests clear records only in this marked disposable database.
- `OPENROUTER_API_KEY`: needed for real agent runs, never for tests.
- `MODEL_NAME`: optional OpenRouter model override.
- `BACKEND_URL`: defaults to `http://127.0.0.1:8000`.

Development data is stored in the ignored `.local/postgres` directory. Press Enter in the database terminal to stop Postgres; restarting the launcher retains saved decisions/payments and refreshes the connection settings.

For an existing local Postgres installation, create separate development and test databases, set their loopback/socket connection strings in `.env`, then run:

```text
uv run -m backend.manage init
uv run -m backend.manage seed
uv run -m backend.manage init-test
npm run dev
```

Initialization creates only the private `undercover` schema and its tables. Seeding adds the 25 queue claims and reference data without overwriting existing state. No evaluation or manual files are loaded.

Open `http://localhost:5173`; the backend runs on port 8000. Select a waiting claim and choose **Run claim**. An approval above $1,000 waits for handler sign-off; then choose **Simulate payment**. No real payment is made.

## Reset and run the queue

To start over, stop `npm run dev` and keep Postgres running, then run:

```text
npm run db:rebuild
```

This deletes application records, including decisions, sign-offs, payments, runs and activity, in the database selected by `DATABASE_URL`. It reloads the 25 claims and reference records from the allowed `data/` files, plus the backend's agent instructions. The reload is transactional: a loading error preserves the previous data. It does not change `.env` or the separate test database. Normal `seed` preserves existing records; `rebuild` replaces them.

Restart `npm run dev`, then run this in another terminal:

```text
npm run claims:run
```

The script processes a snapshot of waiting claims sequentially through `BACKEND_URL`, printing each run's status. It uses the backend's configured model and `OPENROUTER_API_KEY`, so real runs may incur API charges. Completed, in-progress and waiting-for-sign-off claims are skipped. Recorded failures are reported while remaining claims continue; the command exits with status 1 if any failed. Connection/API errors or a 150-second polling timeout stop the batch for inspection.

Over-limit payouts still require handler sign-off in the dashboard. Refresh the queue to see updates. Ctrl+C stops the script, but the current backend run may still finish. Rerunning processes only claims still waiting, including failed undecided claims.

The equivalent Python commands are `uv run -m backend.manage rebuild` and `uv run -m agent.batch`. Both npm commands work on macOS and Windows.

## Tests

With the development database launcher running, use `npm run check`. For a temporary test server instead, run:

```text
uv run -m e2e.local
```

Copy the printed `TEST_DATABASE_URL` line into `.env`, replacing any previous value. Keep that terminal open and run `npm run check` in another terminal. Press Enter in the helper terminal to stop and delete the test database; update the URL each time you start a new one.

First test initialization requires an empty application schema; it refuses to relabel an existing application database as disposable. Loopback aliases and different logins to the same server/database are treated as the same target. Tests cannot point at development.

`npm run check` runs all checks; `npm run check:python` and `npm run check:ts` run the unit checks separately. Playwright uses ports 8010 and 5174, a marked test database and a delayed scripted model. It never reuses the development servers or calls OpenRouter.

## Verification

- Local Postgres: 25 seeded waiting claims, three plans and three handlers. Repeat seeding preserves decisions/payments, and saved state survives a backend restart. Private application tables have RLS enabled.
- Python: 64 tests pass with 97.89% coverage; formatting, lint and types pass. Coverage includes payment boundaries/concurrency, scoped tools, time/iteration limits, failures after committed actions, local connection enforcement, database isolation, a real Postgres stop/restart test, transactional rebuild/rollback and sequential processing of 25 claims with mocked HTTP responses.
- Dashboard: 13 tests pass with over 99% statement coverage. Playwright MCP checks confirm the 25-claim desk, full documents/history, read-only instructions, keyboard focus and desktop/mobile layouts with no horizontal overflow or application console errors.
- Playwright: eight end-to-end scenarios cover approve/decline/refer, live work, duplicate starts, the exact $1,000 boundary, blocked agent payment, handler sign-off, simulated payment, failure display and refresh persistence. MCP also verifies the sign-off flow and saved payment after a backend restart.
- Production dashboard build and frontend secret scan pass. No live model calls were made, and model decision accuracy has not been evaluated.
- `npm run check` passes against the configured local databases. The development dashboard returns 25 claims with no console errors, and its data remains unchanged after the test suite. Database connection details are absent from the production frontend build.

## Pilot limits

Run one backend process. Business records persist in Postgres, but agent execution is not durable: stopping the backend during a run can leave a claim in progress and requires inspection before manual recovery. Completed decisions are immutable, and failed runs preserve committed decisions/payments. There is no sign-in, real payment or customer messaging.

## Harness implementation

Phase 1 adds repeatable schema upgrades, stored parent runs/tasks, global run ownership, transactional distinct-claim admission and two-failure accounting. Python verification: 69 tests, 96.83% coverage, formatting/lint/types pass against a temporary marked test database. Queue model orchestration and the dashboard are pending. No development rebuild or live model run has been performed.

Phase 2 adds versioned wording/manual section lookup, bounded text search, exact per-attempt read evidence and separate backend-owned instruction sets. New decisions retain manual version 2026.2; legacy records stay nullable. Python verification: 79 tests, 97.21% coverage. Synthetic scenarios exercise manual tool paths; they do not measure model decision accuracy.

Phase 3 adds the HTTP-only queue agent, summary-only coordinator tools and fresh claim workers. The shared default is `deepseek/deepseek-v4.1-flash` with low reasoning effort; overrides remain supported. Scripted models verify reversed work ordering, five-claim/uncapped/oversized caps, named and empty queues, clean worker histories and evidence isolation. Python: 84 tests, 97.50% coverage. Provider availability remains unverified.

Phase 4 adds bounded model retry middleware (SDK retries disabled), two-attempt named recovery, one fresh coordinator recovery, expiry cleanup and startup interruption recovery. Late agent payments are attempt-scoped. Lost decision/payment responses are reconciled against saved records, and permitted unpaid approvals recover without another decision. A separate test terminates and restarts a real backend process. Python: 97 tests, 96.63% coverage; all checks pass without provider calls.
