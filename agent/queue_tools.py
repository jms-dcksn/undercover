"""Queue planning tools and delegation polling over the backend API."""

import asyncio
import json
from datetime import UTC, datetime

import httpx
from langchain_core.tools import BaseTool, tool

POLL_SECONDS = 0.2


async def wait_for_attempt(client: httpx.AsyncClient, path: str, attempt: dict) -> str:
    """Watch one attempt and return only its saved short result."""
    claim_id = attempt["claim_id"]
    deadline = datetime.fromisoformat(attempt["deadline"].replace("Z", "+00:00"))
    while datetime.now(UTC) < deadline:
        response = await client.get(f"/api/claims/{claim_id}/run")
        response.raise_for_status()
        current = response.json()
        if current["id"] != attempt["id"]:
            raise RuntimeError("Claim attempt ownership changed.")
        if current["state"] != "running":
            response = await client.get(path)
            response.raise_for_status()
            return next(
                task["result"]
                for task in response.json()["tasks"]
                if task["claim_id"] == claim_id
            )
        await asyncio.sleep(POLL_SECONDS)
    raise TimeoutError("Claim attempt exceeded its deadline.")


async def existing_attempt(
    client: httpx.AsyncClient, path: str, claim_id: str
) -> dict | None:
    """Resume watching admitted work after a lost delegation response."""
    response = await client.get(path)
    response.raise_for_status()
    parent = response.json()
    active = any(
        task["claim_id"] == claim_id and task["state"] == "in_progress"
        for task in parent["tasks"]
    )
    if not active:
        return None
    response = await client.get(f"/api/claims/{claim_id}/run")
    response.raise_for_status()
    attempt = response.json()
    if attempt["parent_id"] != parent["id"]:
        raise RuntimeError("Claim attempt belongs to another queue run.")
    return attempt


def queue_tools(client: httpx.AsyncClient, run_id: str) -> list[BaseTool]:
    """Expose persisted planning and bounded delegation, never child transcripts."""
    path = f"/api/agent/runs/{run_id}"

    async def call(method: str, suffix: str, body: dict | None = None) -> str:
        response = await client.request(method, path + suffix, json=body)
        if response.is_error:
            return json.dumps(
                {"status": response.status_code, "error": response.json()}
            )
        return response.text

    @tool
    async def list_queue() -> str:
        """Read summary-only snapshot claims and the persisted plan."""
        return await call("GET", "/claims")

    @tool
    async def write_todos(tasks: list[dict[str, str]]) -> str:
        """Store ordered claim_id, description and state tasks; retain admitted work."""
        return await call("PUT", "/tasks", {"tasks": tasks})

    @tool
    async def work_claim(claim_id: str) -> str:
        """Delegate a planned claim to a fresh helper; return its saved short result."""
        existing = await existing_attempt(client, path, claim_id)
        if existing:
            return await wait_for_attempt(client, path, existing)
        response = await client.post(path + "/delegate", json={"claim_id": claim_id})
        if response.is_error:
            return json.dumps(
                {"status": response.status_code, "error": response.json()}
            )
        attempt = response.json()
        return await wait_for_attempt(client, path, attempt)

    @tool
    async def reconcile() -> str:
        """Check missing claims, remaining cap slots and mandatory retries."""
        return await call("GET", "/reconciliation")

    @tool
    async def complete_run() -> str:
        """Recheck coverage and save the backend's authoritative outcome summary."""
        return await call("POST", "/complete")

    return [list_queue, write_todos, work_claim, reconcile, complete_run]
