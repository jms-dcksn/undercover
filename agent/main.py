"""The UnderCover Agent."""

import asyncio
import os

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent.retry import middleware
from agent.tools import claim_tools

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
MAX_STEPS = 40


def backend() -> httpx.AsyncClient:
    """Return a client for the UnderCover backend."""
    return httpx.AsyncClient(
        base_url=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"), timeout=30
    )


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
        timeout=45,
        max_retries=0,
    )


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the agent on one claim and return its final reply."""
    return asyncio.run(asyncio.wait_for(arun(claim_id, thread_id, llm), timeout=120))


async def arun(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the claim agent asynchronously with backend-supplied instructions."""
    async with backend() as client:
        instructions = await client.get("/api/agent/instructions")
        instructions.raise_for_status()
        response = await client.get(f"/api/claims/{claim_id}/run")
        response.raise_for_status()
        current = response.json()
        if current["thread_id"] != thread_id or current["state"] != "running":
            raise ValueError("Claim thread does not match an active run.")
        agent = create_agent(
            llm or model(),
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
