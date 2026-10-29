"""Queue planning through HTTP, with no claim evidence in coordinator context."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool

from agent import main
from agent.retry import middleware

POLL_SECONDS = 0.2
STEPS_PER_CLAIM = 24
BASE_STEPS = 20


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


async def arun(run_id: UUID, llm: BaseChatModel | None = None) -> str:
    """Start a fresh coordinator conversation from stored tasks and short results."""
    async with main.backend() as client:
        response = await client.get(f"/api/agent/runs/{run_id}")
        response.raise_for_status()
        parent = response.json()
        instructions = await client.get("/api/agent/instructions")
        instructions.raise_for_status()
        count = min(
            len(parent["snapshot"]), parent["claim_limit"] or len(parent["snapshot"])
        )
        agent = create_agent(
            llm or main.model(),
            middleware=[middleware()],
            tools=queue_tools(client, str(run_id)),
            system_prompt=instructions.json()["queue"],
        )
        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "Work this stored queue run: " + json.dumps(parent),
                    }
                ]
            },
            config={
                "configurable": {"thread_id": parent["thread_id"]},
                "recursion_limit": BASE_STEPS + count * STEPS_PER_CLAIM,
            },
        )
        return result["messages"][-1].text
