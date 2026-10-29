"""Explicit isolated browser-test server: uv run -m e2e.server."""

import os

import uvicorn

from backend import coordinator, db, runs
from e2e import fixtures, model


def main() -> None:
    """Serve the real API with a disposable database and a scripted model."""
    os.environ["DATABASE_URL"] = db.test_database_url()
    os.environ["BACKEND_URL"] = "http://127.0.0.1:8010"
    os.environ["OPENROUTER_API_KEY"] = ""
    fixtures.prepare()
    runs.arun = model.run
    coordinator.arun = model.run_queue
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8010)


if __name__ == "__main__":
    main()
