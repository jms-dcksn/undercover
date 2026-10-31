"""Shared fixtures restricted to an explicitly marked disposable database."""

from uuid import uuid4

import httpx
import pytest

from agent import http
from backend import db, manage
from backend.main import app


@pytest.fixture
def database(monkeypatch):
    url = db.test_database_url()
    monkeypatch.setenv("DATABASE_URL", url)
    manage.initialize()
    with db.connect() as connection:
        purpose = connection.execute(
            "SELECT payload FROM settings WHERE key = 'purpose'"
        ).fetchone()
        if purpose != {"payload": {"value": "test"}}:
            pytest.fail("Run uv run -m backend.manage init-test on the test database.")
        connection.execute(
            "TRUNCATE customers, plans, policies, handlers, claims, runs, "
            "decisions, sign_offs, payments, activity RESTART IDENTITY CASCADE"
        )
        connection.execute("DELETE FROM settings WHERE key != 'purpose'")
    manage.seed()
    return url


@pytest.fixture
def claim_run(database):
    run_id = str(uuid4())
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO claims (id, policy_id, customer_id, state, payload) "
            "SELECT 'TEST-CLAIM', policy_id, customer_id, 'in_progress', "
            "jsonb_set(payload, '{claim_id}', '\"TEST-CLAIM\"') "
            "FROM claims WHERE id = 'CLM-1001'"
        )
        connection.execute(
            "INSERT INTO runs (id, claim_id, thread_id, state, deadline) "
            "VALUES (%s, 'TEST-CLAIM', 'test-thread', 'running', "
            "now() + interval '60 seconds')",
            (run_id,),
        )
    return run_id


@pytest.fixture
def http_backend(monkeypatch):
    monkeypatch.setattr(
        http,
        "backend",
        lambda: httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ),
    )
