# Status

The pilot and harness use FastAPI, local Postgres, LangChain and React. One queue agent chooses the order of a waiting-claim snapshot, stores its to-do list and delegates each claim to a fresh helper. Evidence stays in that helper; the parent receives summaries and saved one-line outcomes.

Handlers can start all waiting claims, a positive distinct-claim cap (the trial input defaults to five), or one selected claim. The dashboard restores the latest run after refresh, polls across gaps between claims, and retains terminal summaries. Claim screens show full evidence, activity, exact versioned sections read and sign-off/payment controls. The instructions screen shows the exact queue and claim prompts.

## Setup and upgrades

Install dependencies, then start everything in one terminal (macOS or Windows):

```text
uv sync
npm install
npm start
```

`npm start` prepares local Postgres before launching the backend and dashboard. Press Ctrl+C to stop them together; database files persist. To run storage and the app in separate terminals instead, use `uv run -m backend.local`, then:

```text
npm run dev
```

Open `http://localhost:5173`; FastAPI runs on port 8000. The launcher keeps data in ignored `.local/postgres`, initializes/upgrades the schema, seeds the 25 development claims and prepares a separate marked test database. It updates only `DATABASE_URL` and `TEST_DATABASE_URL` in ignored `.env`. In storage-only mode, press Enter to stop Postgres without deleting its data.

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

## Langfuse tracing

The repository-local skill is checked in at `.agents/skills/langfuse`; it does not install into user configuration. `UPSTREAM.md` records its source revision. The application uses Langfuse Python 5.1.0, pinned in `uv.lock`, and the native LangChain callback integration.

Set these in the ignored root `.env`, then restart the backend:

```text
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_CAPTURE_CONTENT=false
```

Use the base URL for your project region or self-hosted instance. SDK v5 requires Langfuse Cloud or self-hosted v4.59.0+. Missing keys/base URL or `LANGFUSE_TRACING_ENABLED=false` disables application tracing without initializing a client. Credentials remain server-side.

Each queue/named run has a lifecycle observation, with nested agents, model generations, tools and claim attempts. W3C trace context crosses the delegation HTTP request; callbacks run inline so the delegated helper nests under `work_claim`. Backend session IDs are saved parent-run IDs, grouping related work and retries; the synchronous `agent.main.run` entry point uses its supplied thread ID. Stable names, run/claim identifiers, stored completion/failure state, model name and provider-reported token usage support debugging and cost analysis. Langfuse computes cost when its pricing table recognizes the model; no estimated token usage is invented. Exports run in the background, flush before synchronous calls return and drain on backend exit.

By default an export allowlist excludes prompts, claim evidence, tool arguments/results, model replies, arbitrary metadata and error messages. Only operational identifiers/state and model/usage/timing fields are exported. `LANGFUSE_CAPTURE_CONTENT=true` enables full framework payloads for approved synthetic-data debugging; those payloads can contain personal and medical information. Restart after changing tracing settings. Normal tests force tracing off; tracing tests use an in-memory exporter and stub models.

Implementation follows the current [LangChain integration](https://langfuse.com/integrations/frameworks/langchain), [trace best practices](https://langfuse.com/docs/observability/best-practices) and [export-stage masking](https://langfuse.com/docs/observability/features/masking) guidance. Instrumentation does not change claim decisions, payment checks or persisted run state.

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

## Code boundaries

- `telemetry.py` owns optional SDK initialization, export masking, trace context and shutdown. It imports no agent/backend modules and holds no business state. Agent transport injects context; backend routes pass it to background workers; workers/coordinators trace their existing execution and report saved outcomes. LangChain callbacks belong to each fresh agent invocation.
- `agent/config.py` owns model setup and the backend origin shared by agents and CLI. `agent/http.py` owns async HTTP transport, activity and lost-response recovery. `tools.py` and `queue_tools.py` define the scoped tools; `main.py` and `queue.py` compose the claim and queue conversations. Neither imports the other's entry point.
- `backend/main.py` wires HTTP routes to operations. `worker.py` and `coordinator.py` execute agents; `runs.py`, `queue_runs.py` and `recovery.py` manage stored lifecycle state. `actions.py` owns decision/sign-off/payment rules. `records.py` supplies shared transactional record, lock, activity and active-attempt helpers. Storage modules do not import agent execution.
- `dashboard/src/api.ts` owns HTTP requests and error formatting; `useResource.ts` owns React resource loading and polling. Queue and claim actions share the POST helper. Components use relative API paths; `VITE_API_PROXY` configures the development proxy.

Python dependency tests reject cycles, internal entry-point imports, agent-to-backend imports, agent imports below backend execution and agent service origins outside configuration. Dashboard lint keeps React/polling out of HTTP transport and prevents importing the browser entry point. Review responsibility boundaries as part of every change; these checks cannot prove separation by themselves.

## Verification

Run `npm run check` with the storage launcher running. It runs Python lint/format/types/tests, dashboard lint/format/types/tests and Playwright serially with the existing coverage thresholds. Do not overlap database-backed diagnostics and Playwright: fixtures reset shared test data.

For an independent temporary test database, run `uv run -m e2e.local`, follow its printed connection instructions, and keep that terminal open. This database is deleted when the helper exits; update the test URL on each launch.

Verified locally on October 31, 2026 after Langfuse instrumentation, with `npm run check` against temporary marked test Postgres:

- Python: 121 tests, 97.45% coverage; format, lint and types pass. Includes masked in-memory traces, HTTP delegation nesting, model/token capture, tracing opt-out, repeated synchronous calls with flushing, failure/cancellation handling, launcher startup order, exit status and interruption cleanup, dependency boundaries, default/overridden backend configuration, pilot-schema upgrades without data loss, scoped HTTP tools, caps/concurrent ownership, exact section evidence, retries/exhaustion, lost responses, payment boundaries and a real backend process restart.
- Dashboard: 20 tests, 98.85% statement coverage; format, lint and types pass. The browser suite checks mobile fit and application console errors. Earlier interactive harness checks covered desktop/mobile layout and visible keyboard focus; those interactive checks were not repeated for this refactor.
- Playwright: nine scenarios pass through real HTTP and test Postgres, including capped task progress, retries, two failures left for a handler, reconciliation, refresh, section evidence and existing decision/sign-off/payment flows.
- Earlier checks also verified the production dashboard build, credential scan and rejection of forbidden imports. These checks were not repeated for tracing.

Langfuse ingestion was separately verified with a synthetic stub-model queue run in the disposable test database. The CLI retrieved 63 observations, including 16 generations. The audit confirmed one trace, delegated nesting under `work_claim`, agent/tool/generation types, session grouping, synthetic model/token fields, stored completion state and default content masking. Runtime/scope metadata added by the SDK contains standard environment, service and SDK identifiers. No paid model call or development-data reset was used.

Automated models are scripted and never contact OpenRouter. The development and test targets remain separate; development storage was not rebuilt or used for live model calls during implementation. Live default-model acceptance and decision accuracy remain unverified: rebuilding development outcomes and spending API credit on exactly five claims require explicit authorization. See the remaining checkbox in `docs/PLAN_HARNESS.md`.
