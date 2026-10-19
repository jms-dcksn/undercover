"""Shared fixtures restricted to an explicitly marked disposable database."""

import pytest

from backend import db, manage


@pytest.fixture
def database(monkeypatch):
    url = db.test_database_url()
    monkeypatch.setenv("DATABASE_URL", url)
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
