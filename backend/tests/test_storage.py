import sys
from decimal import Decimal
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb

from backend import actions, db, manage
from backend.models import DecisionInput, PaymentInput, SignOffInput


def test_seed_is_repeatable_and_preserves_state(database):
    with db.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS count FROM claims"
        ).fetchone() == {"count": 25}
        assert connection.execute(
            "SELECT count(*) AS count FROM claims WHERE state = 'waiting'"
        ).fetchone() == {"count": 25}
        connection.execute("UPDATE claims SET state = 'decided' WHERE id = 'CLM-1001'")
        connection.execute(
            "INSERT INTO settings VALUES ('cents', %s)",
            (Jsonb({"items": [{"amount": "1000.01"}]}),),
        )
    manage.seed()
    with db.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS count FROM claims"
        ).fetchone() == {"count": 25}
        assert connection.execute(
            "SELECT state FROM claims WHERE id = 'CLM-1001'"
        ).fetchone() == {"state": "decided"}
        assert connection.execute("SELECT count(*) AS count FROM plans").fetchone() == {
            "count": 3
        }
        assert connection.execute(
            "SELECT count(*) AS count FROM handlers"
        ).fetchone() == {"count": 3}
        row = connection.execute(
            "SELECT payload FROM settings WHERE key = 'cents'"
        ).fetchone()
        assert row is not None
        assert Decimal(row["payload"]["items"][0]["amount"]) == Decimal("1000.01")


def test_seed_reads_only_allowed_files(database, monkeypatch):
    paths = []
    read = Path.read_text

    def tracked_read(path, *args, **kwargs):
        paths.append(path.name)
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracked_read)
    manage.seed()
    assert set(paths) == {
        "plans.json",
        "company.json",
        "customers.json",
        "policies.json",
        "handlers.json",
        "claims.json",
        "policy_wording.md",
        "instructions.md",
    }
    with db.connect() as connection:
        company = connection.execute(
            "SELECT payload FROM settings WHERE key = 'company'"
        ).fetchone()
        assert company is not None
        assert "repeat_claim_review" not in company["payload"]


def test_rebuild_clears_outcomes_and_reloads_seed_records(claim_run):
    actions.decide(
        "TEST-CLAIM",
        DecisionInput(
            run_id=claim_run,
            outcome="approve",
            payout=Decimal("1250.00"),
            explanation="The delay is covered. Eligible expenses total $1250.00.",
            policy_section=3,
        ),
    )
    actions.sign_off("TEST-CLAIM", SignOffInput(handler_id="HND-01"))
    actions.pay("TEST-CLAIM", PaymentInput(amount=Decimal("1250.00")))
    with db.connect() as connection:
        connection.execute("UPDATE customers SET payload = '{}' WHERE id = 'CUS-3001'")
        connection.execute("UPDATE settings SET payload = '{}' WHERE key = 'wording'")
    manage.rebuild()
    with db.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS count FROM claims WHERE state = 'waiting'"
        ).fetchone() == {"count": 25}
        assert connection.execute(
            "SELECT count(*) AS count FROM claims"
        ).fetchone() == {"count": 25}
        assert connection.execute(
            "SELECT (SELECT count(*) FROM decisions) + "
            "(SELECT count(*) FROM sign_offs) + (SELECT count(*) FROM payments) + "
            "(SELECT count(*) FROM runs) + (SELECT count(*) FROM activity) AS count"
        ).fetchone() == {"count": 0}
        assert connection.execute(
            "SELECT payload ->> 'name' AS name FROM customers WHERE id = 'CUS-3001'"
        ).fetchone() == {"name": "Maya Patel"}
        wording = connection.execute(
            "SELECT payload FROM settings WHERE key = 'wording'"
        ).fetchone()
        assert wording is not None
        assert (
            wording["payload"]["text"]
            == (manage.DATA / "policy_wording.md").read_text()
        )
        assert connection.execute(
            "SELECT payload FROM settings WHERE key = 'purpose'"
        ).fetchone() == {"payload": {"value": "test"}}


def test_rebuild_rolls_back_if_seed_loading_fails(database, monkeypatch, tmp_path):
    with db.connect() as connection:
        connection.execute("UPDATE claims SET state = 'decided' WHERE id = 'CLM-1001'")
    monkeypatch.setattr(manage, "DATA", tmp_path)
    with pytest.raises(FileNotFoundError):
        manage.rebuild()
    with db.connect() as connection:
        assert connection.execute(
            "SELECT state FROM claims WHERE id = 'CLM-1001'"
        ).fetchone() == {"state": "decided"}
        assert connection.execute(
            "SELECT count(*) AS count FROM claims"
        ).fetchone() == {"count": 25}
        assert connection.execute(
            "SELECT count(*) AS count FROM settings WHERE key = 'wording'"
        ).fetchone() == {"count": 1}


def test_private_schema(database):
    with db.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS count FROM pg_tables "
            "WHERE schemaname = 'undercover' AND NOT rowsecurity"
        ).fetchone() == {"count": 0}
        assert connection.execute(
            "SELECT count(*) AS count FROM pg_namespace n, "
            "aclexplode(n.nspacl) a WHERE n.nspname = 'undercover' "
            "AND a.grantee = 0 AND a.privilege_type = 'USAGE'"
        ).fetchone() == {"count": 0}


def test_database_configuration(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="Set TEST_DATABASE_URL"):
        db.test_database_url()
    monkeypatch.setenv("DATABASE_URL", "postgresql://one@localhost/dev")
    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql://two@localhost/dev?sslmode=disable"
    )
    with pytest.raises(RuntimeError, match="must differ"):
        db.test_database_url()
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://localhost/test")
    assert db.test_database_url() == "postgresql://localhost/test"


def test_loopback_connection_aliases(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://one@localhost:5432/undercover")
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql://two@[::1]:5432/undercover?sslmode=disable",
    )
    with pytest.raises(RuntimeError, match="must differ"):
        db.test_database_url()
    assert db.database_identity("postgresql://localhost/test") == db.database_identity(
        "postgresql://127.0.0.1:5432/test"
    )


def test_init_test_refuses_existing_application(database, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["manage", "init-test"])
    with db.connect() as connection:
        connection.execute("DELETE FROM settings WHERE key = 'purpose'")
    monkeypatch.delenv("DATABASE_URL")
    try:
        with pytest.raises(RuntimeError, match="existing application"):
            manage.main()
    finally:
        monkeypatch.setenv("DATABASE_URL", database)
        with db.connect() as connection:
            connection.execute(
                "INSERT INTO settings VALUES ('purpose', %s)",
                (Jsonb({"value": "test"}),),
            )


@pytest.mark.parametrize("command", ["init", "seed", "init-test", "rebuild"])
def test_manage_command(command, database, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["manage", command])
    monkeypatch.delenv("DATABASE_URL") if command == "init-test" else None
    manage.main()
    assert f"Database {command} complete." in capsys.readouterr().out
