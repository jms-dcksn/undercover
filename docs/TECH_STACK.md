# Tech stack

- `backend/`: FastAPI and local Postgres through psycopg. `uv run -m backend.local` starts persistent development storage and a separate local test database using pgserver. Database connections use loopback addresses or local sockets. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount.
- `agent/`: LangChain `create_agent` on OpenRouter. One queue agent chooses work from summary-only snapshot access and a stored to-do list, delegating each claim to a fresh helper. Claim and queue agents use HTTP only and share model configuration: `deepseek/deepseek-v4.1-flash` with low reasoning effort by default, or `MODEL_NAME`. Claim helpers retrieve versioned policy/manual sections as needed; the backend saves exact read evidence. Model retry middleware allows one transient retry with SDK retries disabled. The named claim/thread entry point remains available. Parent ownership, tasks, attempts and failures persist in Postgres; startup/expiry cleanup releases interrupted work. Conversations run in one backend process and are not resumed after restart.
- `dashboard/`: React, Vite and TypeScript.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from. The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. The OpenRouter key is `OPENROUTER_API_KEY` in `.env`.

Development data lives in `.local/postgres`, outside git. `DATABASE_URL` and `TEST_DATABASE_URL` select different local databases; the launcher updates both in the ignored `.env` and preserves other settings. An existing local Postgres installation can supply those URLs instead.
