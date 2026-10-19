"""A delayed scripted model for observable end-to-end tool execution."""

import asyncio

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent.main import arun
from e2e.fixtures import SCENARIOS


class ScriptedModel(GenericFakeChatModel):
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
    if claim_id == "E2E-FAIL":
        await asyncio.sleep(0.5)
        raise RuntimeError("Synthetic model failure")
    outcome, payout = SCENARIOS[claim_id]
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
        call("read_policy_wording", {}, "2"),
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
    return await arun(claim_id, thread_id, ScriptedModel(messages=iter(replies)))
