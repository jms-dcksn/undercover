# Tech stack

- `backend/`: FastAPI and local Postgres through psycopg. `uv run -m backend.local` starts persistent development storage and a separate local test database using pgserver. Database connections use loopback addresses or local sockets. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount.
- `agent/`: LangChain's `create_agent` on OpenRouter, with one entry point that takes a claim id and a thread id. It reaches claims and its instructions only through the backend's API. It uses `openai/gpt-6-luna` with low reasoning effort by default, or the model in the environment variable `MODEL_NAME` if set, such as `openrouter/free`. A future extension will add long-term application-scoped memory backed by local Postgres.
- `dashboard/`: React, Vite and TypeScript.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from. The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. The OpenRouter key is `OPENROUTER_API_KEY` in `.env`.

Development data lives in `.local/postgres`, outside git. `DATABASE_URL` and `TEST_DATABASE_URL` select different local databases; the launcher updates both in the ignored `.env` and preserves other settings. An existing local Postgres installation can supply those URLs instead.
