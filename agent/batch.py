"""Process waiting claims sequentially through the running backend."""

import argparse
import os
import time
from uuid import uuid4

import httpx
from dotenv import load_dotenv

WAIT_SECONDS = 150


def wait_for_run(client: httpx.Client, path: str) -> str:
    """Wait for completion or failure without starting another claim."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        state = response.json()["state"]
        if state != "running":
            return state
        time.sleep(1)
    raise TimeoutError("Run did not finish; inspect the claim before continuing.")


def run(client: httpx.Client) -> int:
    """Process one snapshot of waiting claims and return the failure count."""
    response = client.get("/api/claims")
    response.raise_for_status()
    queue = response.json()
    claims = [claim for claim in queue if claim["state"] == "waiting"]
    print(
        f"Processing {len(claims)} waiting claims; {len(queue) - len(claims)} skipped.",
        flush=True,
    )
    failed = 0
    for index, claim in enumerate(claims, 1):
        claim_id = claim["claim_id"]
        print(f"[{index}/{len(claims)}] {claim_id}: starting", flush=True)
        path = f"/api/claims/{claim_id}/run"
        response = client.post(path, json={"thread_id": str(uuid4())})
        response.raise_for_status()
        state = wait_for_run(client, path)
        failed += state == "failed"
        print(f"  {claim_id}: {state}", flush=True)
    print(f"Finished: {len(claims) - failed} completed, {failed} failed.", flush=True)
    return failed


def main() -> None:
    """Run the queue against BACKEND_URL and report failures through the exit code."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    load_dotenv()
    try:
        with httpx.Client(
            base_url=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"), timeout=30
        ) as client:
            failed = run(client)
    except (httpx.HTTPError, TimeoutError) as error:
        raise SystemExit(f"Batch stopped: {error}") from error
    except KeyboardInterrupt:
        print("Stopped. The current agent run may still finish in the backend.")
        raise SystemExit(130) from None
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
