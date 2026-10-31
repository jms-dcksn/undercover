# Review of the Agent code after harness implementation


below are coding issues we should fix:

- too many hard coded URLs
- Too many imports across modules - e.g. queue.py imports main?? this is not good.
- The harness is spread across different files and mixes responsibilities in those feals we need better clean separation of duties e.g. harness and business rules


Confirm these issues exist - do you agree?

If yes, fix them.

Investigate whether similar issues exist in backend and dashboard code. We need clean, idiomatic code.

Retest after fixing.

Update PROCESS.md and CODE_STANDARDS.md and STATUS.md so that this never happens again.

## Response

Agree with the responsibility and dependency concerns. Import count alone is not a useful quality measure, and multiple cohesive harness files are appropriate. The concrete problems were:

- The agent and CLI repeated the backend origin default. Model/client setup lived in `agent/main.py`, forcing `queue.py` to depend on an entry point. Shared configuration now lives in `agent/config.py`.
- Claim tools mixed tool schemas with HTTP activity/error/recovery handling. Queue orchestration mixed agent construction with tool definitions and delegation polling. Transport now lives in `agent/http.py`; claim and queue tools have separate modules.
- Backend run persistence imported and executed the agent. Execution now lives in `backend/worker.py`. Queue and run storage also imported common lock/activity helpers from business actions; these now live in `backend/records.py`, along with shared active-attempt validation.
- Dashboard HTTP transport also owned React polling, and queue start duplicated POST serialization. The hook now lives in `useResource.ts`, and queue start uses the shared HTTP helper. No circular product imports or direct database access from dashboard components were found.

Stable `/api` paths remain beside their operations. The dashboard already uses relative paths and a configurable proxy; replacing those with a global route registry would add unnecessary indirection.

`PROCESS.md`, `CODE_STANDARDS.md` and `STATUS.md` now document ownership and review requirements. Dependency tests and dashboard lint enforce concrete boundaries. These reduce recurrence; no process can guarantee that mixed responsibilities never return.

## Verification

`npm run check` passes: 108 Python tests (96.59% coverage), 20 dashboard tests (98.85% statement coverage) and nine Playwright scenarios, with format/lint/type gates intact. Tests used temporary marked Postgres and scripted models. Production dashboard build and the configured-credential scan pass; forbidden dashboard imports were separately checked against the lint restrictions. No live model calls or development rebuilds were performed.
