"""A delayed scripted model for observable end-to-end tool execution."""

import asyncio

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agent import main, queue
from agent.main import arun
from backend import db
from e2e.fixtures import SCENARIOS


class ScriptedModel(FakeMessagesListChatModel):
    """Use deterministic messages while exercising LangChain's real tool loop."""

    def bind_tools(self, tools, **kwargs):
        return self

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(0.5)
        return await super()._agenerate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )


def call(name: str, arguments: dict, identifier: str) -> AIMessage:
    """Script one actual tool call."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": arguments,
                "id": identifier,
            }
        ],
    )


async def run(claim_id: str, thread_id: str) -> str:
    """Run only synthetic scenarios and never instantiate an OpenRouter model."""
    with db.connect() as connection:
        attempts = connection.execute(
            "SELECT count(*) AS n FROM runs WHERE claim_id = %s", (claim_id,)
        ).fetchone()
    if claim_id in ("E2E-FAIL", "HARNESS-TWICE") or (
        claim_id == "HARNESS-RETRY" and attempts and attempts["n"] == 1
    ):
        await asyncio.sleep(0.5)
        raise RuntimeError("Synthetic model failure")
    outcome, payout = SCENARIOS.get(claim_id, ("decline", "0.00"))
    explanations = {
        "approve": f"The documented carrier delay is covered by section 3. "
        f"Eligible hotel costs are ${payout}, below the First plan's $1,500 limit.",
        "decline": "The incident occurred outside the covered trip dates. "
        "Section 9 excludes this loss.",
        "refer": "The required hotel receipt is missing. "
        "Refer for the document required by section 3.",
    }
    replies = [
        call("read_claim", {}, "1"),
        call("read_section", {"document": "wording", "section": 3}, "2"),
        call("read_section", {"document": "manual", "section": 7}, "manual"),
        call("read_company", {}, "3"),
        call(
            "record_decision",
            {
                "outcome": outcome,
                "payout": payout,
                "explanation": explanations[outcome],
                "policy_section": 9 if outcome == "decline" else 3,
            },
            "4",
        ),
    ]
    if outcome == "approve":
        replies.append(call("request_payment", {"amount": payout}, "5"))
    replies.append(AIMessage(content="Decision recorded."))
    return await arun(claim_id, thread_id, ScriptedModel(responses=[*replies]))


async def run_queue(run_id):
    """Script the parent separately from each fresh child model through real HTTP."""
    async with main.backend() as client:
        response = await client.get(f"/api/agent/runs/{run_id}")
        response.raise_for_status()
        parent = response.json()
    ids = sorted(
        parent["snapshot"], key=lambda value: (not value.startswith("HARNESS-"), value)
    )
    ids = ids[: parent["claim_limit"] or len(ids)]
    tasks = [
        {"claim_id": claim_id, "description": "Assess claim", "state": "todo"}
        for claim_id in ids
    ]
    messages = [
        call("list_queue", {}, "list"),
        call("write_todos", {"tasks": tasks}, "plan"),
    ]
    for index, claim_id in enumerate(ids):
        messages.append(call("work_claim", {"claim_id": claim_id}, f"claim-{index}"))
        if claim_id in ("HARNESS-RETRY", "HARNESS-TWICE"):
            messages.append(call("reconcile", {}, f"missing-retry-{index}"))
            messages.append(call("complete_run", {}, f"premature-finish-{index}"))
            messages.append(
                call("work_claim", {"claim_id": claim_id}, f"retry-{index}")
            )
    messages.extend(
        [
            call("reconcile", {}, "reconcile"),
            call("complete_run", {}, "complete"),
            AIMessage(content="Saved"),
        ]
    )
    return await queue.arun(run_id, ScriptedModel(responses=[*messages]))
