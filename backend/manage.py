"""Local database setup: uv run -m backend.manage init|seed|init-test|rebuild."""

import argparse
import json
import os
from pathlib import Path
from typing import LiteralString, cast

from psycopg import sql
from psycopg.types.json import Jsonb

from backend import documents
from backend.db import Connection, Row, connect, test_database_url

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def initialize() -> None:
    """Create the private schema without changing existing business records."""
    with connect() as connection:
        schema = cast(LiteralString, Path(__file__).with_name("schema.sql").read_text())
        connection.execute(schema)
        documents.load(connection, DATA)


def insert_records(
    connection: Connection, table: str, records: list[Row], keys: dict[str, str]
) -> None:
    """Insert seed records without overwriting existing rows."""
    statement = sql.SQL(
        "INSERT INTO {} ({}, payload) VALUES ({}, %s) ON CONFLICT DO NOTHING"
    ).format(
        sql.Identifier("undercover", table),
        sql.SQL(", ").join(map(sql.Identifier, keys)),
        sql.SQL(", ").join(sql.Placeholder() for _ in keys),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            statement,
            [
                (*[record[source] for source in keys.values()], Jsonb(record))
                for record in records
            ],
        )


def seed() -> None:
    """Load only the pilot's allowed business files."""
    with connect() as connection:
        seed_records(connection)


def seed_records(connection: Connection) -> None:
    """Load seed records within the caller's transaction."""
    documents.load(connection, DATA)
    plans = json.loads((DATA / "plans.json").read_text())
    company = json.loads((DATA / "company.json").read_text())
    settings = {
        "company": {
            key: company[key]
            for key in (
                "name",
                "currency",
                "payout_approval_limit",
                "policy_wording_version",
            )
        },
        "plan_terms": {key: value for key, value in plans.items() if key != "plans"},
        "wording": {"text": (DATA / "policy_wording.md").read_text()},
        "instructions": {
            "text": Path(__file__).with_name("instructions.md").read_text()
        },
    }
    insert_records(
        connection,
        "customers",
        json.loads((DATA / "customers.json").read_text()),
        {"id": "customer_id"},
    )
    insert_records(connection, "plans", plans["plans"], {"id": "plan"})
    insert_records(
        connection,
        "policies",
        json.loads((DATA / "policies.json").read_text()),
        {"id": "policy_id", "customer_id": "customer_id", "plan": "plan"},
    )
    insert_records(
        connection,
        "handlers",
        json.loads((DATA / "handlers.json").read_text()),
        {"id": "handler_id", "can_sign_off": "can_approve_over_limit"},
    )
    insert_records(
        connection,
        "claims",
        json.loads((DATA / "claims.json").read_text()),
        {"id": "claim_id", "policy_id": "policy_id", "customer_id": "customer_id"},
    )
    for key, payload in settings.items():
        connection.execute(
            "INSERT INTO settings VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (key, Jsonb(payload)),
        )


def rebuild() -> None:
    """Replace application data from the allowed seed files atomically."""
    initialize()
    with connect() as connection:
        connection.execute(
            "TRUNCATE customers, plans, policies, handlers, claims, runs, "
            "decisions, sign_offs, payments, activity, queue_runs, tasks, "
            "section_reads, document_sections RESTART IDENTITY CASCADE"
        )
        connection.execute("DELETE FROM settings WHERE key != 'purpose'")
        seed_records(connection)


def initialize_test() -> None:
    """Mark a separate local database as disposable without relabeling app data."""
    url = test_database_url()
    development = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        with connect() as connection:
            existing = connection.execute(
                "SELECT to_regnamespace('undercover') AS schema"
            ).fetchone()
            if existing and existing["schema"]:
                purpose = connection.execute(
                    "SELECT payload FROM settings WHERE key = 'purpose'"
                ).fetchone()
                if purpose != {"payload": {"value": "test"}}:
                    raise RuntimeError(
                        "Refusing to mark an existing application schema "
                        "as disposable. "
                        "Choose an empty test database."
                    )
        initialize()
        with connect() as connection:
            connection.execute(
                "INSERT INTO settings VALUES ('purpose', %s) ON CONFLICT DO NOTHING",
                (Jsonb({"value": "test"}),),
            )
    finally:
        if development is None:
            del os.environ["DATABASE_URL"]
        else:
            os.environ["DATABASE_URL"] = development


def main() -> None:
    """Run the selected explicit setup operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "seed", "init-test", "rebuild"])
    command = parser.parse_args().command
    if command == "init-test":
        initialize_test()
    elif command == "init":
        initialize()
    elif command == "rebuild":
        rebuild()
    else:
        seed()
    print(f"Database {command} complete.")


if __name__ == "__main__":
    main()
