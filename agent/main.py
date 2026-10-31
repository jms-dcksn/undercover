"""The UnderCover Agent."""

import asyncio

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

from agent import config, http
from agent.retry import middleware
from agent.tools import claim_tools

MAX_STEPS = 40


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the agent on one claim and return its final reply."""
    return asyncio.run(asyncio.wait_for(arun(claim_id, thread_id, llm), timeout=120))


async def arun(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the claim agent asynchronously with backend-supplied instructions."""
    async with http.backend() as client:
        instructions = await client.get("/api/agent/instructions")
        instructions.raise_for_status()
        response = await client.get(f"/api/claims/{claim_id}/run")
        response.raise_for_status()
        current = response.json()
        if current["thread_id"] != thread_id or current["state"] != "running":
            raise ValueError("Claim thread does not match an active run.")
        agent = create_agent(
            llm or config.model(),
            middleware=[middleware()],
            tools=claim_tools(client, claim_id, current["id"]),
            system_prompt=instructions.json()["text"],
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": f"Decide claim {claim_id}."}]},
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": MAX_STEPS,
            },
        )
        return result["messages"][-1].text
