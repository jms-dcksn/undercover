# Status

Pilot implementation is in progress. Phases 1–2 add private Postgres storage, repeatable seed loading and read APIs for the queue, full claims, policy wording, company, handlers and agent instructions. The agent and dashboard are still the initial skeleton.

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
- Python checks: 15 tests passed, 96% coverage; lint, formatting and types pass. API tests verify full claim documents/history, the read-only instructions and required operation metadata.
- Supabase development initialization, API exposure and restart checks are pending connection details. No Supabase project has been modified.
