"""Queue planning through HTTP, with no claim evidence in coordinator context."""

import json
from uuid import UUID

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

import telemetry
from agent import config, http
from agent.queue_tools import queue_tools
from agent.retry import middleware

STEPS_PER_CLAIM = 24
BASE_STEPS = 20


async def arun(run_id: UUID, llm: BaseChatModel | None = None) -> str:
    """Start a fresh coordinator conversation from stored tasks and short results."""
    async with http.backend() as client:
        response = await client.get(f"/api/agent/runs/{run_id}")
        response.raise_for_status()
        parent = response.json()
        instructions = await client.get("/api/agent/instructions")
        instructions.raise_for_status()
        count = min(
            len(parent["snapshot"]), parent["claim_limit"] or len(parent["snapshot"])
        )
        agent = create_agent(
            llm or config.model(),
            middleware=[middleware()],
            tools=queue_tools(client, str(run_id)),
            system_prompt=instructions.json()["queue"],
            name="queue-agent",
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
                "callbacks": telemetry.callbacks(),
                "configurable": {"thread_id": parent["thread_id"]},
                "recursion_limit": BASE_STEPS + count * STEPS_PER_CLAIM,
            },
        )
        return result["messages"][-1].text
