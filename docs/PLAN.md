# Pilot plan

Build a local claims platform around the existing FastAPI, LangChain and React skeleton. Use Supabase/Postgres as specified in `TECH_STACK.md`. Keep the policy decision with the agent and enforce payment rules in the backend.

Approved for implementation. Database checks against Supabase remain pending until the development connection is provided; local checks use a disposable Postgres instance.

## Scope and decisions for review

- Load the 25 claims in `data/claims.json`, their supporting records and the full `data/policy_wording.md`. The agent reads the customer's existing claim history but does not use the claims manual.
- Start one selected claim from the dashboard. Keep `run(claim_id, thread_id)` as the agent entry point. Use a background task so the API and dashboard remain responsive while it runs.
- Store business state and visible activity in Postgres. Agent execution remains in one backend process; durable graph execution, a dispatcher, long-term memory and automatic restart recovery are later work.
- Keep sign-in, real payments, customer messages, evaluation tooling, security-lab features and AWS deployment out of scope. Never read or import `data/evals/` or `data/security/`.
- Tests use a stub model and a dedicated disposable Postgres database. No test calls OpenRouter or uses a shared business database.

### Decision card: storage

**Recommendation:** connect FastAPI to Supabase Postgres with the existing psycopg dependency. Keep database credentials server-side and application tables in a private schema accessed through FastAPI. The dashboard and agent use HTTP only.

**Proposed shape:** keyed customer, policy, plan, handler and claim records; company settings and policy wording; separate decisions, sign-offs, simulated payments, runs and activity records. Preserve nested seed documents as JSONB rather than splitting every receipt and traveler into tables. Use typed columns for identifiers, relationships, workflow state, money and timestamps. Use decimal amounts in Python and `NUMERIC` in Postgres.

**Why:** this follows the edited tech stack, keeps the pilot small and makes the payment check and write transactional. It avoids introducing a second storage implementation for tests.

**Prerequisite and impact:** before implementation touches a database, identify a dedicated development target and a separate disposable test target. Review this schema proposal before applying it. No paid plan, project provisioning or changes to an existing shared database are assumed. Keep connection details in ignored environment configuration and placeholders in setup documentation.

Use the connection string supplied by Supabase; select direct or session-pooler connectivity for the local persistent backend based on network support. See [database connections](https://supabase.com/docs/guides/database/connecting-to-postgres) and [API exposure](https://supabase.com/docs/guides/api/securing-your-api). Verify current guidance during implementation.

## Workflow contract

Queue state, decision and payment state are separate:

| Queue label | Meaning |
| --- | --- |
| Waiting | Seeded claim or a failed attempt available for manual retry. |
| In progress | One agent run owns the claim. |
| Waiting for sign-off | The agent approved more than $1,000; payment is blocked. |
| Decided | Declined, referred, approved for at most $1,000, or approved with recorded handler sign-off. |

An approval remains an `approve` decision when it needs sign-off. A referral is a completed decision with an explanation; collecting missing documents and resuming it are outside this pilot. Show unpaid and paid approvals separately from queue state so a failed payment is visible.

The agent can record a decision and request payment. Only the handler screen offers sign-off, using a handler record permitted to approve over the limit. With no sign-in, this is a workflow boundary, not authenticated proof of who clicked; the pilot must not be exposed as a production payment service.

## Phase 1: Postgres storage and seed data

Create the reviewed schema, database access module and explicit initialization/seed commands. Import only an allowlist of business files. Convert seed claim status `open` to `waiting`. Import the supplied reference records without adding any other claims to the queue. Store the read-only agent instructions in the backend so the screen and agent share one source.

Keep schema setup separate from normal application startup. Seeding must be repeatable without overwriting decisions, payments or activity. Use a private application schema with no access for Supabase's public API roles; do not expose database credentials in Vite configuration.

Success criteria:

- [ ] Document cross-platform `uv run` commands for initialization and seeding, plus development/test connection variables. Confirm the selected database targets before running schema changes.
- [ ] Run initialization and seeding on the dedicated development database; a count query returns exactly 25 queue claims, all initially waiting, with valid customer and policy relationships, three plans and three handlers.
- [x] Seed twice; counts are unchanged. Create a synthetic decision, seed again and verify that the decision and workflow state survive.
- [ ] A synthetic write/read test preserves nested documents and exact cents. Restart the backend and confirm saved business state remains available.
- [x] Tests prove the loader opens only the named seed files and never traverses evaluation, security or manual files; no evaluation answers appear in application storage.
- [ ] Verify the application schema is outside Data API exposure and public API roles lack access. Verify database secrets are absent from browser-facing responses and assets.
- [x] Run `npm run check:python`; lint, formatting, types and tests pass with at least 80% Python coverage.

## Phase 2: Read APIs and claim details

Add typed API responses for the queue, a full claim, its policy and plan, customer history, company payout limit, handlers, policy wording and agent instructions. A claim detail response should preserve the story, every item and all supporting document text. Keep the agent's lookup access tied to the selected claim and its linked records.

Proposed operations:

| Method and path | Purpose |
| --- | --- |
| `GET /api/health` | Preserve the existing health response. |
| `GET /api/claims` | Queue summaries, including workflow and payment state. |
| `GET /api/claims/{claim_id}` | Claim, linked policy/plan, customer/history and recorded outcome. |
| `GET /api/policy-wording` | Full wording and version. |
| `GET /api/company` | Company name, currency and payout approval limit. |
| `GET /api/handlers` | Handler names and sign-off eligibility. |
| `GET /api/agent/instructions` | The exact read-only instructions used by the agent. |

Success criteria:

- [x] `GET /api/health` returns `200 {"status":"ok"}`. `GET /api/claims` returns 25 records with the documented queue state values.
- [x] `GET /api/claims/CLM-1001` returns the complete claim, `POL-2001`, its Premium plan and the linked customer's existing history. Compare against the allowed source files.
- [x] An unknown claim returns `404` with a useful error. Read APIs never return database credentials or arbitrary filesystem content.
- [x] Wording and instructions endpoints return the expected full text; there is no API for modifying instructions or fetching the manual/evaluation data.
- [x] An OpenAPI test verifies unique `operation_id` values, one-line route docstrings and required inputs only for every operation.
- [x] Run `npm run check:python`; all checks and coverage pass.

## Phase 3: Decisions, sign-off and simulated payment

Implement explicit backend operations for recording a decision, signing it off and paying it. Require an outcome, a nonnegative payout, two or three explanatory sentences and a policy section reference for a decision. Declines and referrals require zero payout; an approval reduced to zero by policy terms creates no payment. Validate section references against the supplied wording.

Use the configured $1,000 limit and check the full recorded payout, not the amount in an individual payment request. Payment is a separate operation whose required amount must equal that payout. Lock the claim while checking and writing so concurrent calls cannot bypass sign-off or create duplicate payments. Completed decisions are immutable in this pilot; sign-off is tied to that decision and payout.

| Method and path | Required body |
| --- | --- |
| `POST /api/claims/{claim_id}/decision` | Run ID, outcome, payout, explanation and policy section reference. |
| `POST /api/claims/{claim_id}/sign-off` | Eligible handler ID. |
| `POST /api/claims/{claim_id}/payment` | Amount in USD. |

Success criteria, using synthetic claims in the disposable test database:

- [x] Approved payouts of `$999.99` and `$1,000.00` can be simulated without sign-off. `$1,000.01` produces waiting-for-sign-off and payment returns `409` with no payment record.
- [x] A direct API payment attempt before sign-off fails, including an attempt to pay only `$1,000.00` against a larger approved payout. A prompt cannot override the backend rule.
- [x] An unknown handler is rejected; a handler without over-limit permission is rejected with `403`. An eligible handler can sign off; the same full payout can then be simulated and the queue shows decided.
- [x] Declined, referred and undecided claims cannot be paid. Negative, zero and malformed payment amounts return `422`; amounts that differ from the approval return `409`.
- [x] Repeating the same sign-off/payment returns the recorded result without another write. Concurrent payment calls produce one payment record; concurrent decision submissions cannot replace a completed decision.
- [x] Read responses distinguish the original outcome, sign-off and payment. All money remains exact to the cent. Each mutation has a tested error response and OpenAPI metadata.
- [x] Run `npm run check:python`; all checks and coverage pass.

## Phase 4: Agent execution and visible activity

Replace the hello-world agent with the claims workflow using the existing `create_agent` and OpenRouter model configuration. Fetch instructions from the backend before creating the agent. Tools fetch the selected claim context and policy wording, submit the decision and request payment through HTTP; the agent never imports backend storage or reads seed files. Do not give it a sign-off tool.

Instructions require the agent to assess coverage, calculate the payout from policy terms, cite the relevant section and explain the result in two or three sentences. Missing information or unresolved judgment results in a referral. Use company settings only for the operational payout gate; do not supply manual-only handling rules as policy context.

Add `POST /api/claims/{claim_id}/run` with a required thread ID and `GET /api/claims/{claim_id}/activity`. Atomically claim a waiting item, return `202` with a run ID, then execute it in the background. Reject duplicate starts with `409`. Record ordered, timestamped steps such as context retrieval, tool calls/results, decision, blocked payment, completion and failure. Show observable work, not hidden model reasoning.

On failure, record the error and return an undecided claim to waiting for manual retry. Preserve a decision or payment already recorded; never restart and pay it again blindly. Bound execution time and tool iterations. Interrupted process recovery is a documented pilot limitation, not a durable execution system.

Success criteria:

- [x] Stub-model tests cover approve, decline and refer, including payout arithmetic and section references on synthetic policy examples. No test makes a live model call.
- [x] HTTP-client assertions prove the agent fetches its instructions, context and wording through the backend and sends all changes through mutation endpoints. Its tool list contains no sign-off, SQL or filesystem tool.
- [x] A stub that tries to pay an over-limit approval receives the backend rejection; the claim stays waiting for sign-off with no payment record, and the run ends normally.
- [ ] Starting a stub run returns `202`; another start for the same claim returns `409`. Health and activity requests remain responsive during execution.
- [ ] Polling activity shows ordered tool steps before completion, then the saved decision. No fabricated progress or private reasoning appears.
- [x] Model/tool failures and iteration/time limits end visibly. Tests verify retry behavior before a decision and preservation of committed decisions/payments after a later failure.
- [x] Default model, low reasoning setting and `MODEL_NAME` override remain covered by configuration tests without contacting OpenRouter.
- [x] Run `npm run check:python`; all checks and coverage pass.


## Phase 5: Handler dashboard

Build a queue and claim detail view with a clear selected claim. Include all claim documents, linked policy/plan, customer history, decision, payout, policy reference, sign-off/payment status and live activity. Add a read-only instructions view. Poll while a run is active and refresh the queue after mutations; no WebSocket or Supabase Realtime dependency is needed.

Offer a run button for waiting claims, a handler selector/sign-off action for eligible approvals and a separate simulated payment action for approved unpaid claims. Automatically simulate eligible payments through the agent; the manual action also permits completing a payment after sign-off or a failed agent payment. Display backend errors and block repeated submissions while a request is pending.

Use Instrument Sans, Instrument Serif where an accent is useful, JetBrains Mono for identifiers/numbers, the specified brand colors and rounded panels. Format money as US dollars, provide text labels alongside status colors and keep controls keyboard accessible.

Success criteria:

- [x] Vitest covers queue/detail selection, document rendering, instructions, loading/empty/error states and allowed controls for all four queue states. `npm run check:ts` passes with at least 80% dashboard coverage.
- [x] In a browser, verify the 25-item queue, full detail for `CLM-1001`, linked history, every attached document and the exact read-only instructions text.
- [ ] With a delayed stub run, observe in-progress state and new activity before the outcome appears. Refreshing the page preserves saved state and restores the activity view.
- [ ] A synthetic over-limit approval shows the amount and waiting-for-sign-off status; payment is unavailable until an eligible handler signs off. Simulating payment updates both detail and queue without duplication.
- [x] Check keyboard navigation, visible focus, readable color contrast, USD formatting and layout at desktop and narrow mobile widths. Browser checks produce no application console errors.
- [x] Use the Playwright MCP server for the interactive checks described above when available. If unavailable, use an available browser tool and retain equivalent Playwright test evidence; report any unverified visual check explicitly.


## Phase 6: End-to-end verification and handover

Wire Playwright to a dedicated test backend and disposable Postgres database, with a deterministic stub model selected only by explicit test configuration. Fail fast if test database configuration is missing or points at the development target. Test cleanup must affect only test-owned data. Normal development uses the configured OpenRouter model.

Document setup, environment placeholders, schema/seed commands, how to start the app and agent workflow, how to run checks, and the single-process execution limitation in `docs/STATUS.md`. Keep setup commands compatible with macOS and Windows; use `uv run` commands or `.mjs` helpers for new scripts.

Success criteria:

- [ ] `npm run dev` starts the backend on port 8000 and dashboard on port 5173. The documented setup seeds 25 claims without reading the answer key.
- [ ] Playwright exercises queue → full claim → start run → live activity → approved/declined/referred decision → updated queue, using stubbed model output through the real backend and Postgres.
- [ ] Playwright covers an over-limit approval, a rejected direct payment before sign-off, eligible handler sign-off and one successful simulated payment. Exactly `$1,000.00` is also covered without sign-off.
- [ ] End-to-end checks cover duplicate run prevention, visible failures, refresh persistence and the read-only instructions page. Tests run without `OPENROUTER_API_KEY` and never call a model.
- [ ] `npm run check` exits successfully: Python formatting/lint/types/tests, TypeScript formatting/lint/types/tests and Playwright, with the existing coverage thresholds intact.
- [ ] `docs/STATUS.md` accurately describes the delivered product and commands. Tick criteria only after verification; record any missing prerequisite or unverified check explicitly.

## Implementation discipline

After review and an implementation request, build the phases in order. For each phase, add tests, verify every criterion, tick the completed boxes, update `docs/STATUS.md` and commit with the pre-commit hook enabled. Never push. Run the full check suite after the final phase.

Automated checks establish workflow and payment-control correctness. They do not establish handler-level model accuracy. A paid live-model smoke run requires explicit authorization; evaluation against `data/evals/` remains separate future work and requires permission to open it.
