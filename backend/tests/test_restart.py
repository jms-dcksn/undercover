import asyncio
import os
import socket
import sys
import time

import httpx

from backend import db, queue_runs
from backend.tests.test_queue_runs import parent, plan


async def launch_backend(port):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--port",
        str(port),
        env={**os.environ, "OPENROUTER_API_KEY": ""},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=1)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if client.get("/api/health").status_code == 200:
                return process, client
        except httpx.ConnectError:
            await asyncio.sleep(0.05)
    process.terminate()
    await asyncio.wait_for(process.wait(), timeout=5)
    raise TimeoutError("Test backend did not start.")


async def restart_scenario():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process, client = await launch_backend(port)
    try:
        run = parent(1)
        plan(run, run.snapshot[:1])
        attempt = queue_runs.delegate(run.id, run.snapshot[0])
    finally:
        client.close()
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5)
    process, client = await launch_backend(port)
    try:
        saved = client.get(f"/api/agent/runs/{run.id}").json()
        assert saved["state"] == "failed"
        assert "interrupted" in saved["error"]
        assert (
            client.get(f"/api/claims/{attempt.claim_id}").json()["summary"]["state"]
            == "waiting"
        )
        with db.connect() as connection:
            assert connection.execute(
                "SELECT count(*) AS n FROM runs WHERE state = 'running'"
            ).fetchone() == {"n": 0}
        assert attempt.claim_id in parent(1).snapshot
    finally:
        client.close()
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5)


def test_process_restart_releases_interrupted_claim(database):
    asyncio.run(restart_scenario())
