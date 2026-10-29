# Status

The pilot and harness use FastAPI, local Postgres, LangChain and React. One queue agent chooses the order of a waiting-claim snapshot, stores its to-do list and delegates each claim to a fresh helper. Evidence stays in that helper; the parent receives summaries and saved one-line outcomes.

Handlers can start all waiting claims, a positive distinct-claim cap (the trial input defaults to five), or one selected claim. The dashboard restores the latest run after refresh, polls across gaps between claims, and retains terminal summaries. Claim screens show full evidence, activity, exact versioned sections read and sign-off/payment controls. The instructions screen shows the exact queue and claim prompts.

## Setup and upgrades

Install and start storage in one terminal (macOS or Windows):

```text
uv sync
npm install
uv run -m backend.local
```

Keep it running, then start the app in another terminal:

```text
npm run dev
```

Open `http://localhost:5173`; FastAPI runs on port 8000. The launcher keeps data in ignored `.local/postgres`, initializes/upgrades the schema, seeds the 25 development claims and prepares a separate marked test database. It updates only `DATABASE_URL` and `TEST_DATABASE_URL` in ignored `.env`. Press Enter in the storage terminal to stop Postgres without deleting its data.

For an existing local Postgres installation, stop the backend, configure distinct development/test databases in `.env`, then run:

```text
uv run -m backend.manage init
uv run -m backend.manage seed
uv run -m backend.manage init-test
npm run dev
```

`init` applies the repeatable additive harness upgrade and loads versioned document sections/instructions. Run it before starting an upgraded backend. Existing decisions, payments, activity and runs survive repeated initialization. `seed` preserves existing business records. New decisions record manual version 2026.2; legacy decisions retain null provenance. No evaluation or security data is loaded.

Configuration:

- `DATABASE_URL`: local development storage, normally database `undercover`.
- `TEST_DATABASE_URL`: a different disposable local database, normally `undercover_test`.
- `OPENROUTER_API_KEY`: required only for real model runs.
- `MODEL_NAME`: optional override; default `deepseek/deepseek-v4.1-flash` with low reasoning effort. Arbitrary overrides do not force that provider setting.
- `BACKEND_URL`: agent/CLI backend, default `http://127.0.0.1:8000`.

Connections accept local sockets or loopback hosts only. Test setup rejects aliases or alternate logins pointing at the development database and refuses to mark existing application data disposable.

## Running work

With the app and Postgres running:

```text
npm run claims:run
npm run claims:run -- --limit 5
npm run claims:run -- --claim CLM-1001
```

These commands start one backend parent run and watch its persisted progress; the model chooses queue order. `--limit` and `--claim` are mutually exclusive. Repeating the command while work is active attaches to that run. Ctrl+C stops watching, while backend work may continue. Polling follows the parent deadline rather than a fixed single-claim timeout. Failed parent runs and exhausted technical failures return a nonzero exit code. Real runs may spend API credit.

To delete development outcomes and reload the allowed business files, stop the app, keep Postgres running and explicitly run:

```text
npm run db:rebuild
```

Rebuild clears decisions, sign-offs, payments, parent runs, tasks, attempts, failure counts, activity and read evidence, then loads the 25 claims, reference records, wording/manual index and instructions transactionally. It preserves `.env` and the separate test database. Restart the app before running work. Every live trial must rebuild first and use a five-claim cap; do not run an uncapped live trial.

## Limits and recovery

Run one backend process. Postgres stores business outcomes and ownership; model conversations are not durable and are not resumed after restart.

- The parent snapshots waiting, undecided claims. New arrivals wait for another run. Decided, sign-off and needs-handler claims are excluded.
- One active parent covers both queue and named work. Delegation atomically reserves one distinct-claim cap slot and one active attempt. Retries reuse the slot.
- An undecided claim's first failed attempt returns it to waiting for retry during the run. Its second failure, counted across runs/restarts since rebuild, sets `needs_handler`. This is a technical failure with no insurance decision. A `refer` decision is separate and always has zero payout.
- Model middleware retries transient failures once per step, with SDK retries disabled. Attempts have 120-second and 40-step limits. Parent time/step budgets grow with scope and the two-attempt allowance. A failed coordinator gets one fresh invocation from saved tasks/results, then fails visibly.
- Reconciliation blocks completion while admitted work is active, requires a first-failure retry, and catches missed claims within the cap. Summaries count saved decisions, payments, technical failures, handler work and claims outside the cap.
- Startup marks interrupted parents failed and releases unfinished claim ownership. The watchdog cleans up expired work and retries storage cleanup when the database returns. A new run can pick up eligible work; the old model conversation is discarded.
- Saved decisions/payments are preserved. Lost write responses are checked against stored actions; permitted unpaid approvals recover without deciding again. Late attempt writes are rejected. Payments above $1,000 remain blocked until eligible handler sign-off; repeated payments are idempotent. No real payments or customer messages occur.

## APIs

`POST /api/agent/runs` requires `thread_id`, nullable `claim_limit` and nullable `claim_id`. Read `/api/agent/runs/latest` or `/api/agent/runs/{id}` for scope, state, deadline, ordered tasks, attempt/failure details, summary and error. Task/delegation/reconciliation/completion operations live below the run path. The existing named claim run/detail/activity routes remain available.

`GET /api/documents/{document}/sections` lists headings for `wording` or `manual`; `POST /api/documents/search` returns bounded snippets. A scoped attempt reads a section through `/api/claims/{claim}/runs/{attempt}/sections`, saving the exact returned text/version. `/api/claims/{claim}/sections` exposes that claim's read evidence. Claim tools have no whole-document, sign-off, filesystem or database access.

## Verification

Run `npm run check` with the storage launcher running. It runs Python lint/format/types/tests, dashboard lint/format/types/tests and Playwright serially with the existing coverage thresholds. Do not overlap database-backed diagnostics and Playwright: fixtures reset shared test data.

For an independent temporary test database, run `uv run -m e2e.local`, follow its printed connection instructions, and keep that terminal open. This database is deleted when the helper exits; update the test URL on each launch.

Verified locally with `npm run check`:

- Python: 104 tests, 96.58% coverage; format, lint and types pass. Includes pilot-schema upgrades without data loss, scoped HTTP tools, caps/concurrent ownership, exact section evidence, retries/exhaustion, lost responses, payment boundaries and a real backend process restart.
- Dashboard: 20 tests, 98.85% statement coverage. Playwright MCP checks confirm desktop/mobile layout, no horizontal overflow at 390px, visible keyboard focus and zero application console errors.
- Playwright: nine scenarios pass through real HTTP and test Postgres, including capped task progress, retries, two failures left for a handler, reconciliation, refresh, section evidence and existing decision/sign-off/payment flows.
- Production dashboard build and a scan for configured database/API credentials pass.

Automated models are scripted and never contact OpenRouter. The development and test targets remain separate; development storage was not rebuilt or used for live model calls during implementation. Live default-model acceptance and decision accuracy remain unverified: rebuilding development outcomes and spending API credit on exactly five claims require explicit authorization. See the remaining checkbox in `docs/PLAN_HARNESS.md`.
