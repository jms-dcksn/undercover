import psycopg
import pytest
from dotenv import dotenv_values
from pgserver.postgres_server import get_server

from backend import db, local


def test_local_setup_preserves_settings_and_data_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/previous")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://localhost/previous_test")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=unchanged-key\nMODEL_NAME=example-model\n")
    directory = tmp_path / "postgres"
    server = get_server(directory, cleanup_mode="stop")
    try:
        local.configure(server, env_file)
        settings = dotenv_values(env_file)
        assert settings["OPENROUTER_API_KEY"] == "unchanged-key"
        assert settings["MODEL_NAME"] == "example-model"
        development_url = settings["DATABASE_URL"]
        test_url = settings["TEST_DATABASE_URL"]
        assert development_url is not None
        assert test_url is not None
        assert db.database_identity(development_url) != db.database_identity(test_url)
        with db.connect() as connection:
            assert connection.execute(
                "SELECT count(*) AS n FROM claims"
            ).fetchone() == {"n": 25}
            connection.execute(
                "UPDATE claims SET state = 'decided' WHERE id = 'CLM-1001'"
            )
        with psycopg.connect(test_url) as connection:
            assert connection.execute(
                "SELECT payload FROM undercover.settings WHERE key = 'purpose'"
            ).fetchone() == ({"value": "test"},)
    finally:
        server.cleanup()
    restarted = get_server(directory, cleanup_mode="stop")
    try:
        local.configure(restarted, env_file)
        with db.connect() as connection:
            assert connection.execute(
                "SELECT count(*) AS n FROM claims"
            ).fetchone() == {"n": 25}
            assert connection.execute(
                "SELECT state FROM claims WHERE id = 'CLM-1001'"
            ).fetchone() == {"state": "decided"}
        assert dotenv_values(env_file)["OPENROUTER_API_KEY"] == "unchanged-key"
    finally:
        restarted.cleanup()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://database.example/undercover",
        "host=localhost hostaddr=192.0.2.1 dbname=undercover",
    ],
)
def test_remote_connections_are_rejected(url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(db.DatabaseNotConfigured, match="local"):
        db.connect()


def test_local_socket_identity(tmp_path):
    assert db.database_identity(f"host={tmp_path} dbname=undercover") == (
        str(tmp_path.resolve()),
        "5432",
        "undercover",
    )
