import asyncio
import sys
from types import SimpleNamespace

import psycopg
import pytest
from dotenv import dotenv_values
from pgserver.postgres_server import get_server

from backend import db, local


@pytest.mark.parametrize("result", [0, 1, KeyboardInterrupt()])
def test_start_app_waits_for_storage_and_always_stops_it(result, tmp_path, monkeypatch):
    events = []
    server = SimpleNamespace(cleanup=lambda: events.append("stopped"))
    monkeypatch.setattr(sys, "argv", ["local", "--app"])
    monkeypatch.setattr(local, "DATA_DIRECTORY", tmp_path / "postgres")
    monkeypatch.setattr(local, "get_server", lambda *args, **kwargs: server)
    monkeypatch.setattr(local, "configure", lambda *args: events.append("ready"))

    async def app():
        events.append("app")
        if isinstance(result, KeyboardInterrupt):
            raise result
        return result

    monkeypatch.setattr(local, "run_app", app)
    if isinstance(result, KeyboardInterrupt):
        local.main()
    else:
        with pytest.raises(SystemExit) as error:
            local.main()
        assert error.value.code == result
    assert events == ["ready", "app", "stopped"]


def test_dev_command_runs_from_repo_root(monkeypatch):
    calls = []

    async def wait():
        return 3

    async def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(wait=wait)

    monkeypatch.setattr(local.asyncio, "create_subprocess_shell", spawn)
    assert asyncio.run(local.run_app()) == 3
    assert calls == [("npm run dev", {"cwd": local.manage.ROOT})]


def test_interrupt_waits_for_app_shutdown(monkeypatch):
    waits = []

    async def wait():
        waits.append("wait")
        if len(waits) == 1:
            raise asyncio.CancelledError
        return 0

    async def spawn(*args, **kwargs):
        return SimpleNamespace(wait=wait)

    monkeypatch.setattr(local.asyncio, "create_subprocess_shell", spawn)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(local.run_app())
    assert waits == ["wait", "wait"]


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
