# Status

Pilot implementation is in progress. Phases 1–5 add Postgres storage, claims APIs, payment controls, the bounded LangChain agent and the handler dashboard.

The dashboard includes a searchable/filterable queue, full claim evidence, customer history, policy/plan terms, live activity, read-only instructions and handler sign-off/payment controls. It follows the brand and adapts to mobile widths.

The agent fetches its instructions and records through FastAPI and records real tool activity. The API runs it in the background, prevents duplicate starts and preserves committed decisions/payments on failure. The model defaults to `openai/gpt-6-luna` with low reasoning effort unless `MODEL_NAME` is set.

## Setup

Install dependencies with `uv sync` and `npm install`. Copy the placeholders in `.env.example` into your ignored `.env` and supply the connection strings:

- `DATABASE_URL`: dedicated development Supabase Postgres connection, preferably the session pooler on IPv4 networks. Include `sslmode=require` for hosted connections.
- `TEST_DATABASE_URL`: separate disposable Postgres database. Tests delete application records in this database. It must differ from development.
- `OPENROUTER_API_KEY`: needed for real agent runs, never for tests.
- `MODEL_NAME`: optional OpenRouter model override.
- `BACKEND_URL`: defaults to `http://127.0.0.1:8000`.

After confirming the development target, run:

```text
uv run -m backend.manage init
uv run -m backend.manage seed
uv run -m backend.manage init-test
npm run dev
```

Initialization creates only the private `undercover` schema and its tables. Seeding adds the 25 queue claims and reference data without overwriting existing state. No evaluation or manual files are loaded. Test initialization explicitly marks the separate database as disposable before fixtures may clear its application records.

Run `npm run check` for all checks or `npm run check:python` for Python checks.

## Verification

- Local disposable Postgres: 25 waiting claims, three plans and three handlers; repeat seeding preserves workflow state and nested data. Application tables have RLS enabled.
- Python checks: 45 tests passed, over 99% coverage; lint, formatting and types pass. Tests cover the API/payment controls, scripted approve/decline/refer tool use, blocked agent payment, model configuration, iteration/time limits, retry behavior and failures after committed actions. No model calls were made.
- Dashboard: 13 tests pass with over 99% statement coverage. Playwright MCP checks confirm the 25-claim desk, full documents/history, read-only instructions, keyboard focus and desktop/mobile layouts with no horizontal overflow or application console errors.
- Integrated delayed-agent and sign-off browser flows remain for phase 6.
- Supabase development initialization, API exposure and restart checks are pending connection details. No Supabase project has been modified.
