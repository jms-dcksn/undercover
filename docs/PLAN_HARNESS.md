# Harness plan

Extend the pilot described in `docs/STATUS.md` to meet `docs/HARNESS.md`. Keep FastAPI, local Postgres, LangChain `create_agent`, OpenRouter and the existing dashboard. Build one queue agent that plans and chooses work, delegating each claim to a fresh claim agent. The backend enforces execution and payment limits.

Implementation and automated acceptance are complete. Checked criteria have verification evidence; the separately authorized live trial remains pending. `docs/PLAN.md` stays unchanged.

## Decisions for review

**Recommendation:** run claims sequentially under one queue agent. Give it tools to list eligible claims, maintain its to-do list, delegate a claim and check remaining work. It receives claim summaries and short results; evidence and document contents stay in each claim agent's context. This provides autonomous ordering without introducing another framework or a later-day swarm.

**Storage decision:** add queue-run and task records, link existing claim-attempt records to their parent run, and add a `needs_handler` claim state for exhausted technical failures. Persist document sections, read evidence and the manual version used for new decisions. Apply an explicit, repeatable schema update through the existing initialization command, preserving pilot records; rebuilding development data is not a migration strategy. This schema proposal is part of the plan's review before implementation.

**Recovery decision:** retain one backend process. Recover interrupted ownership from Postgres on startup and return unfinished, undecided claims to waiting or needs-handler according to their attempt count. Do not add a durable graph, checkpoint replay or automatic resumption of the old model conversation. After a process restart, the next queue run picks up eligible work.

The existing pilot already returns an undecided claim to waiting after a caught failure. The missing pieces are automatic retries, an exhaustion boundary and cleanup after process interruption.

## Execution contract

- A queue run snapshots the waiting, undecided claims when it starts. The agent chooses their order. New arrivals belong to the next run; decided, sign-off and needs-handler claims are excluded.
- A cap counts distinct claims admitted to the run, including claims that ultimately fail. Retries use the same slot. A capped run may inspect summary identifiers for the snapshot but may delegate at most the cap; unselected claims remain waiting. An uncapped run covers the snapshot. An empty queue completes with a zero-work summary.
- A named-claim run uses the same claim worker and recovery rules, restricted to that claim. Keep the dashboard's single-claim action and existing claim-run entry point. Adapt `npm run claims:run` into a client that starts and watches one queue run; remove its code-driven claim loop. Support `npm run claims:run -- --limit 5` and `--claim CLM-1001`; reject incompatible flags and nonpositive limits.
- Allow one active top-level run, including named-claim work, with a database-enforced conflict response. Reserve a claim and its cap slot transactionally when delegating. Duplicate or parallel delegation must not create another active attempt or exceed the cap.
- Each undecided claim gets at most two failed whole-claim attempts, counted across runs and restarts since rebuild. On the first failure it returns to waiting and the agent retries it during the current run. On the second it becomes `needs_handler`, with the error visible and no automatic restart. A transient model-call retry happens inside an attempt and does not increment this count.
- `needs_handler` means no insurance decision was recorded. A manual-rule referral remains a recorded `refer` decision with zero payout and a reason. Both can appear as “Left for handler” on the to-do list, as can an approval awaiting sign-off, but the saved outcome and reason distinguish them. Do not invent a referral to represent a technical error.
- Preserve immutable decisions, exact-cent amounts, idempotent payments and the backend sign-off gate above $1,000. If a write response is lost, read the saved result before retrying. A failure after a committed decision must not return the claim to the undecided queue. Recover a permitted unpaid approval without deciding again; leave an unrecoverable payment problem visible for a handler.
- To-do states are `todo`, `in_progress`, `done` and `left_for_handler`. Store stable claim IDs, order and short descriptions. The agent creates and updates the plan; the backend validates terminal statuses against recorded outcomes and keeps attempts, errors and reads authoritative. Plan edits cannot delete admitted work or reset attempts.
- Before completion, the agent must call a reconciliation tool. It compares the snapshot, remaining cap, admitted tasks and actual claim records. Missed eligible claims or a first failed attempt still needing retry prevent successful completion. Recheck this condition when saving completion, so a model's final message alone cannot end the run. Persist a short summary with outcome counts, payments, failures, handler work and claims left outside the cap.

## Phase 1: Persist runs, tasks and ownership

Extend `backend/schema.sql`, models, initialization, queries and run handling. Retain existing per-claim runs as attempt history. Queue runs store mode, scope, cap, state, deadline, summary and timestamps; tasks link the parent run to claims and their persisted plan. Store failure history so starting another run cannot silently reset the two-failure limit.

Add typed HTTP operations to start/read a queue run, read the current or latest run, update its tasks, delegate a claim and reconcile/complete the run. Use `/api/agent/runs` for parent runs and preserve the existing claim detail/activity routes. Delegation returns `202` with an attempt ID; its tool polls that attempt until completion within its deadline, rather than holding one HTTP request open for the whole claim. All agent reads and writes go through these APIs. New operations follow the existing required-input, unique-operation-ID and one-line-docstring rules.

Success criteria:

- [x] Initialize an existing pilot database twice without losing decisions, payments or activity; fresh initialization and transactional rebuild include all new records. Verify private-schema permissions and RLS on new tables.
- [x] A capped start returns `202` with an ID, mode, cap and snapshot; named, uncapped and empty-queue starts have tested responses. Invalid caps return `422`; an unknown named claim returns `404`; competing active starts return `409`.
- [x] Tests persist and reload all four task states and reject duplicate tasks, invalid claim IDs, deleting admitted work and falsely marking undecided work done.
- [x] Concurrent delegation tests enforce one active attempt per claim, one cap slot per distinct claim and no work beyond the cap. Existing decision/payment boundary tests continue to pass.
- [x] OpenAPI contracts pass; `npm run check:python` passes with at least 80% coverage against the separate marked test database.

## Phase 2: Section lookup and claim instructions

Load only the explicitly allowed `data/claims_manual.md` in addition to the pilot files. Split the manual and wording at numbered headings, preserving each section's full text, heading, document identity and version. Use a small section index and text search; these documents do not need embeddings, a vector store or an MCP service.

Provide HTTP tools to list section headings, search both documents with bounded snippets and read a named section. Replace the claim agent's whole-wording tool. Record each successful section read against the active attempt, with source, version, section and the exact text returned, so the claim screen can show what it read. The model receives no whole document by default.

Separate queue and claim instructions in backend-owned files and expose both through the read-only instructions API. Include any middleware-added instructions in what handlers can inspect. The policy controls coverage; the manual supplies interpretation and handling rules. Instructions require relevant benefit, general exclusions, document, history and calculation checks, followed by targeted section reads. Add the manual version to new decision records; preserve legacy decisions without inventing provenance.

Success criteria:

- [x] Seed/index tests reproduce numbered sections and versions exactly, including tables and interpretation notes. Search returns matching section references; unknown documents/sections return `404` and empty searches have an explicit empty result.
- [x] The loader allowlist includes the manual but never opens `data/evals/` or `data/security/`. Agent tools expose neither filesystem/database access nor handler sign-off.
- [x] HTTP and stub-model tests prove section lookup replaces the full-document tool, retrieved text reaches only the scoped claim worker, and successful reads persist with their exact source text/version.
- [x] Synthetic scenarios exercise a third claim in 12 months, wild-animal loss and meals without receipts through manual reads. Also cover missing evidence versus an explicitly unmet condition, and a payout reduced to zero being declined. Referral explanations can state a potential payable amount while the saved referral payout remains zero.
- [x] Both instruction texts match the prompts actually supplied, including mandatory middleware additions; new decisions record the manual version. `npm run check:python` passes.

## Phase 3: Queue agent and fresh claim helpers

Build the queue agent with the existing LangChain tool loop. Give it summary-only queue access, a persisted `write_todos` tool with the four required states, a `work_claim` delegation tool and reconciliation. A small custom planning tool fits these states directly; the installed standard to-do middleware supports only three states and does not by itself persist this dashboard contract.

Each delegation creates a new claim agent and message history bound to the claim and attempt IDs. Reuse the claim tools and payment controls, with section lookup from Phase 2. The delegation waits for that attempt and returns one line derived from saved records: decision/payout/payment status or failure. No child messages, tool transcripts or customer documents flow back into the queue context. Retries also start clean.

Change the shared default to `deepseek/deepseek-v4.1-flash` with low reasoning effort. Preserve `MODEL_NAME` overrides and the existing behavior of not forcing provider-specific reasoning settings on arbitrary overrides. Queue and claim workers use the same configuration factory.

Success criteria:

- [x] A scripted queue model chooses a deliberately different order from claim-ID order, creates/updates stored tasks, delegates the snapshot and produces a short saved summary. No Python loop preselects its work order.
- [x] A five-claim cap admits exactly five distinct synthetic claims; retries consume no extra slot and remaining claims stay waiting. Test a cap larger than the queue, an empty queue and one named claim.
- [x] Captured worker inputs prove that each claim and retry gets fresh history with no previous customer's evidence. Captured parent inputs contain only summaries and one-line results.
- [x] The helper's result matches saved decisions/payments even if its final model text is inaccurate. Claim activity still records each actual tool call and section read on the correct attempt.
- [x] Configuration tests verify the exact default model, low reasoning effort and overrides without contacting OpenRouter; `npm run check:python` passes.

## Phase 4: Retries, reconciliation and interruption cleanup

Use LangChain middleware for bounded retries of transient provider failures such as timeouts, rate limits and server errors. Keep retries in one layer, disabling duplicate SDK retries. Use at most two provider calls per failed model step, with short backoff inside the claim attempt's deadline. Do not retry authentication failures or deterministic validation/sign-off rejections as transient errors.

Keep explicit per-attempt time and tool-step limits. Derive the parent time/step budget from its eligible claim count and two-attempt allowance, allowing a full queue to run longer than the pilot's single-claim 120-second timeout. Bound coordinator recovery as well: after exhausted provider retries, allow one fresh coordinator invocation reconstructed from stored tasks and short outcomes. If it still fails, record a visible run failure and release ownership safely.

Catch failures at the delegation boundary, finalize the attempt transactionally and return an error result so the parent can continue. Reconcile authoritative records after ambiguous decision/payment responses. Startup cleanup and timeout cleanup must be idempotent, preserve committed business actions and reject writes from expired or replaced attempts. An unavailable database is a visible failed-run condition; cleanup resumes when storage is available, rather than claiming recovery succeeded.

Success criteria:

- [x] A transient provider failure recovers within its attempt; permanent errors stop bounded retries. Fake clocks or short test budgets verify backoff, timeouts and step limits without slow sleeps.
- [x] One claim fails, returns to waiting, succeeds on retry and does not stop later claims. Another fails twice, becomes needs-handler and is excluded from a subsequent run. Verify the failure count across parent runs and startup cleanup.
- [x] A scripted parent omits an eligible claim or tries to finish before a retry; reconciliation identifies the missing work and successful completion is blocked until it is handled within the cap.
- [x] Lost responses after decision/payment commits, late worker writes and repeated cleanup produce at most one decision and one payment. Test payment recovery after a saved approval and the unchanged `$1,000.00`/`$1,000.01` sign-off boundary.
- [x] Stop/restart a test backend during a run. Its parent is marked interrupted/failed, no claim remains owned in progress, saved decisions/payments survive and a new run can pick up eligible work. Coordinator failure and total-budget exhaustion have equivalent cleanup tests.
- [x] `npm run check:python` passes without live model calls.

## Phase 5: Dashboard and queue command

Add queue-level controls for all waiting claims or a positive claim cap, defaulting the trial input to five. Retain the named-claim action. Show the current run's ordered to-do list, progress, retry/error details and final summary on the queue page. Reload the latest stored run after a refresh and retain its terminal result until another run starts.

Poll based on parent-run status, including gaps between claims and retries when no claim is in progress. Refresh queue/detail data as work changes. Add the needs-handler label/filter and distinguish technical failures from recorded referrals and sign-off work. The claim screen shows expandable sections actually read, including version and attempt. The instructions screen shows queue and claim instructions separately. Follow `docs/BRAND.md` and existing keyboard/mobile patterns.

Update `agent/batch.py` to submit one parent run, poll its stored status and print progress/summary. Its timeout must follow the parent deadline rather than the old fixed 150-second single-claim wait. Ctrl+C stops watching and explains that backend work may continue; rerunning attaches to or reports the active run rather than launching duplicate work.

Success criteria:

- [x] Vitest covers cap validation, active-run controls, all task states, needs-handler filtering, both instruction sets, section-read display and loading/error/empty states. `npm run check:ts` passes with at least 80% coverage.
- [x] In the browser, observe a delayed stub run's list being created, updated and completed. Refresh between claims and verify polling resumes, with no duplicate start or lost summary.
- [x] The claim page shows the exact sections read and their source/version; another claim's evidence does not appear. Named-claim, sign-off and simulated-payment flows still work.
- [x] CLI tests cover uncapped, `--limit 5` and `--claim` starts, bad flags, progress, terminal summaries, failed-run exit status, connection errors and interruption, using mocked HTTP only.
- [x] Use Playwright MCP when available, otherwise an available browser tool plus Playwright evidence, to check desktop/mobile layout, keyboard focus, USD formatting and no application console errors. Record any unavailable visual check explicitly.

## Phase 6: Verification and handover

Extend the existing isolated Postgres/Playwright harness with separate scripted parent and child models. Run database-backed suites serially because their fixtures reset the test data. Update `docs/SPEC.md` to make the manual part of decisions, and update `docs/TECH_STACK.md` and `docs/STATUS.md` for the model, APIs, commands, run states and recovery boundaries. Keep the finished pilot plan intact.

Success criteria:

- [x] Playwright covers capped queue start, stored to-do progress, fresh claim work, section reads, a failure followed by retry, two failures left for a handler, omitted-work reconciliation, refresh persistence and the final summary through real HTTP and test Postgres.
- [x] Existing approve/decline/refer, duplicate-start and sign-off/payment regressions pass. Automated tests run without `OPENROUTER_API_KEY` and never contact a model provider.
- [x] `npm run check` exits successfully with the existing format, lint, type, coverage and end-to-end gates intact. Record the actual results in `docs/STATUS.md`.
- [x] Document cross-platform setup, uncapped/capped/named commands, the destructive rebuild boundary, two-failure behavior and single-process interruption recovery. Verify development and test targets remain separate and the frontend contains no credentials.
- [ ] Separately authorized live acceptance: stop development runs, run `npm run db:rebuild`, restart the app with `MODEL_NAME` unset, then run `npm run claims:run -- --limit 5`. Observe five distinct claims handled autonomously on the default model, visible task updates and per-claim section reads; the other 20 remain waiting. Record actual outcomes and any failure without using evaluation answers. If authorization or provider access is unavailable, leave this criterion unchecked and report the reason.

The real-model acceptance run spends API credit and rebuilding deletes existing development outcomes. Obtain explicit authorization for that pair of operations during implementation. Every live trial must reseed first and use a five-claim cap; do not substitute an uncapped live run. Stub tests verify the configured model string but cannot establish provider availability or decision accuracy.

## Implementation discipline

After review and an implementation request, build the six phases in order. Add tests with each change, verify and tick criteria here, update `docs/STATUS.md` and commit each phase with the pre-commit hook enabled. Run the full suite after the final phase. Never push.

Do not read evaluation answers, change unrelated notebook work, add another agent framework or build later-day durable graphs, swarms, long-term memory, sign-in, customer messaging or AWS resources.


## Verification evidence

- `npm run check`: 102 Python tests (96.61% coverage), 20 dashboard tests (98.85% statement coverage), nine Playwright scenarios; lint, format and type gates pass.
- Tests use a temporary marked Postgres database distinct from development. The upgrade regression starts from pilot table shapes and preserves decisions, payments, activity and null legacy manual provenance through two initializations.
- Real backend process termination/restart releases interrupted ownership; saved-business-action and sign-off boundaries have separate recovery regressions.
- Playwright covers the capped parent, visible plan updates, clean helpers, section reads, retry/exhaustion, premature completion rejection, refresh and final saved summary through real HTTP/Postgres. Playwright MCP confirms desktop/mobile fit, visible keyboard focus and zero application console errors.
- `npx vite build dashboard` and a scan for the configured database/API credential values pass.
- No evaluation/security files were read, no live model calls were made, and development outcomes were not rebuilt. Live acceptance stays unchecked until explicit approval to rebuild development and spend API credit on exactly five claims. Provider availability and real decision accuracy are unverified.
