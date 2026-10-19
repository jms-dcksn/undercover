"""Run persistent local Postgres: uv run -m backend.local."""

import os
from pathlib import Path

import psycopg
from dotenv import set_key
from pgserver.postgres_server import PostgresServer, get_server
from psycopg import sql

from backend import manage

DATA_DIRECTORY = manage.ROOT / ".local" / "postgres"


def configure(server: PostgresServer, env_file: Path) -> None:
    """Create separate local databases and save only their connection settings."""
    with psycopg.connect(server.get_uri(), autocommit=True) as connection:
        for name in ("undercover", "undercover_test"):
            exists = connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone()
            if not exists:
                connection.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
                )
    for key, name in (
        ("DATABASE_URL", "undercover"),
        ("TEST_DATABASE_URL", "undercover_test"),
    ):
        value = server.get_uri(database=name)
        set_key(env_file, key, value)
        os.environ[key] = value
    manage.initialize()
    manage.seed()
    manage.initialize_test()


def main() -> None:
    """Keep the local server running and retain its data after shutdown."""
    DATA_DIRECTORY.parent.mkdir(parents=True, exist_ok=True)
    server = get_server(DATA_DIRECTORY, cleanup_mode="stop")
    try:
        configure(server, manage.ROOT / ".env")
        print("Local Postgres is ready. Connections saved to .env.")
        print("Data is kept in .local/postgres. Run npm run dev in another terminal.")
        input("Press Enter to stop Postgres and retain its data. ")
    finally:
        server.cleanup()


if __name__ == "__main__":
    main()
