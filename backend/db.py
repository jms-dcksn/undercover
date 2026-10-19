"""Postgres connections for the private application schema."""

import os
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

load_dotenv()

type Row = dict[str, Any]
type Connection = psycopg.Connection[Row]


class DatabaseNotConfigured(RuntimeError):
    """The backend has no development database connection."""


def connect() -> Connection:
    """Open a transaction on the configured application database."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise DatabaseNotConfigured("Set DATABASE_URL in the ignored root .env file.")
    return psycopg.Connection[Row].connect(
        url,
        row_factory=dict_row,
        connect_timeout=10,
        options="-c search_path=undercover -c statement_timeout=10000",
    )


def database_identity(url: str) -> tuple[str, str, str, str]:
    """Identify a database without comparing passwords or SSL options."""
    values = conninfo_to_dict(url)
    host = str(values.get("host", "localhost"))
    name = str(values.get("dbname", "postgres"))
    if host.endswith(".pooler.supabase.com"):
        project = str(values.get("user", "")).rsplit(".", 1)[-1]
        return "supabase", project, name, ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return "supabase", host.split(".")[1], name, ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "localhost"
    return (
        host,
        str(values.get("port", "5432")),
        name,
        "",
    )


def test_database_url() -> str:
    """Require an explicitly separate database for destructive test fixtures."""
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        raise RuntimeError("Set TEST_DATABASE_URL to a disposable Postgres database.")
    development = os.environ.get("DATABASE_URL", "")
    if development and database_identity(url) == database_identity(development):
        raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL.")
    return url
