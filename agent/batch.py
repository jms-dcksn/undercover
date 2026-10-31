"""Start or watch one backend-managed queue run."""

import argparse
import time
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import uuid4

import httpx

from agent.config import backend_url


def progress(run: dict) -> str:
    """Render short persisted task states without downloading claim evidence."""
    return "\n".join(
        f"{task['claim_id']}: {task['state']}"
        + (f" — {task['result']}" if task["result"] else "")
        for task in run["tasks"]
    )


def wait_for_run(client: httpx.Client, path: str) -> dict:
    """Poll until terminal state, following the backend's parent deadline."""
    previous = None
    while True:
        response = client.get(path)
        response.raise_for_status()
        run = response.json()
        current = progress(run)
        if current and current != previous:
            print(current, flush=True)
            previous = current
        if run["state"] != "running":
            print(run["summary"] or run["error"] or run["state"], flush=True)
            return run
        deadline = datetime.fromisoformat(run["deadline"].replace("Z", "+00:00"))
        if datetime.now(UTC) > deadline + timedelta(seconds=5):
            raise TimeoutError(
                "Parent deadline exceeded; inspect the stored queue run."
            )
        time.sleep(1)


def run(
    client: httpx.Client, limit: int | None = None, claim_id: str | None = None
) -> int:
    """Start one parent or attach to active work and report technical failures."""
    response = client.get("/api/agent/runs/latest")
    response.raise_for_status()
    active = response.json()
    if active and active["state"] == "running":
        print(f"Watching active run {active['id']}; no new work started.", flush=True)
        parent = active
    else:
        response = client.post(
            "/api/agent/runs",
            json={
                "thread_id": str(uuid4()),
                "claim_limit": limit,
                "claim_id": claim_id,
            },
        )
        if response.status_code == HTTPStatus.CONFLICT:
            response = client.get("/api/agent/runs/latest")
        response.raise_for_status()
        parent = response.json()
        print(f"Watching run {parent['id']}.", flush=True)
    finished = wait_for_run(client, f"/api/agent/runs/{parent['id']}")
    return int(
        finished["state"] == "failed"
        or any(
            task["result"] and "technical failure" in task["result"]
            for task in finished["tasks"]
        )
    )


def positive(value: str) -> int:
    """Require a positive distinct-claim cap."""
    limit = int(value)
    if limit <= 0:
        raise argparse.ArgumentTypeError("The limit must be a positive integer.")
    return limit


def main() -> None:
    """Watch a queue, capped trial or named claim without owning execution order."""
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--limit", type=positive)
    scope.add_argument("--claim")
    args = parser.parse_args()
    try:
        with httpx.Client(base_url=backend_url(), timeout=30) as client:
            failed = run(client, args.limit, args.claim)
    except (httpx.HTTPError, TimeoutError) as error:
        raise SystemExit(f"Queue watch stopped: {error}") from error
    except KeyboardInterrupt:
        print("Stopped watching. Backend work may continue; rerun to watch it.")
        raise SystemExit(130) from None
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
