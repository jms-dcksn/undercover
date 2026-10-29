import asyncio

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import main
from agent.tools import claim_tools
from backend import db


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    def bind_tools(self, tools, **kwargs):
        return self


def reply(name, args, call_id):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
    )


def scripted_model(outcome, amount, pay):
    replies = [
        reply("read_claim", {}, "1"),
        reply("read_section", {"document": "wording", "section": 3}, "2"),
        reply("read_company", {}, "3"),
        reply(
            "record_decision",
            {
                "outcome": outcome,
                "payout": amount,
                "explanation": "Covered expenses total $420.00 under section 3. "
                "The plan's $800.00 limit leaves $420.00 payable.",
                "policy_section": 3,
            },
            "4",
        ),
    ]
    if pay:
        replies.append(reply("request_payment", {"amount": amount}, "5"))
    replies.append(AIMessage(content="Decision recorded."))
    return StubModel(messages=iter(replies))


@pytest.mark.parametrize(
    ("outcome", "amount", "pay"),
    [
        ("approve", "420.00", True),
        ("decline", "0.00", False),
        ("refer", "0.00", False),
        ("approve", "1000.01", True),
    ],
)
def test_run(outcome, amount, pay, claim_run, http_backend):
    assert (
        main.run("TEST-CLAIM", "test-thread", scripted_model(outcome, amount, pay))
        == "Decision recorded."
    )
    with db.connect() as connection:
        saved = connection.execute("SELECT * FROM decisions").fetchone()
        assert saved is not None
        assert saved["outcome"] == outcome
        assert str(saved["payout"]) == amount
        events = connection.execute("SELECT * FROM activity ORDER BY id").fetchall()
        assert events[0]["message"] == "Read claim and supporting records"
        assert "tool_finished" in {event["kind"] for event in events}
        payments = connection.execute("SELECT * FROM payments").fetchall()
        if amount == "1000.01":
            assert not payments
            assert "tool_error" in {event["kind"] for event in events}
        else:
            assert bool(payments) == pay


def test_agent_uses_backend_instructions(claim_run, http_backend, monkeypatch):
    create = main.create_agent
    prompts = []

    def capture(*args, **kwargs):
        prompts.append(kwargs["system_prompt"])
        return create(*args, **kwargs)

    monkeypatch.setattr(main, "create_agent", capture)
    main.run("TEST-CLAIM", "test-thread", scripted_model("refer", "0.00", False))
    with db.connect() as connection:
        stored = connection.execute(
            "SELECT payload FROM settings WHERE key = 'instructions'"
        ).fetchone()
    assert stored is not None
    assert prompts == [stored["payload"]["text"]]


def test_tools_are_scoped_and_reject_wrong_thread(claim_run, http_backend):
    async def names():
        async with main.backend() as client:
            return [tool.name for tool in claim_tools(client, "TEST-CLAIM", claim_run)]

    assert asyncio.run(names()) == [
        "read_claim",
        "list_sections",
        "search_sections",
        "read_section",
        "read_company",
        "record_decision",
        "request_payment",
    ]
    with pytest.raises(ValueError, match="thread"):
        main.run("TEST-CLAIM", "other-thread", scripted_model("refer", "0.00", False))


def test_model_iteration_limit(claim_run, http_backend, monkeypatch):
    monkeypatch.setattr(main, "MAX_STEPS", 2)
    with pytest.raises(Exception, match="Recursion limit"):
        main.run("TEST-CLAIM", "test-thread", scripted_model("refer", "0.00", False))


def test_tool_connection_failure():
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.method == "GET":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json={})

    async def invoke():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), base_url="http://test"
        ) as client:
            tools = claim_tools(client, "TEST-CLAIM", "test-run")
            await tools[0].ainvoke({})

    with pytest.raises(httpx.ConnectError):
        asyncio.run(invoke())
    assert len(calls) == 3


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    default = main.model()
    assert default.model_name == "openai/gpt-6-luna"
    assert default.reasoning_effort == "low"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    override = main.model()
    assert override.model_name == "openrouter/free"
    assert override.reasoning_effort is None


def test_backend_url(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://test-server")
    client = main.backend()
    assert str(client.base_url) == "http://test-server"
    asyncio.run(client.aclose())
