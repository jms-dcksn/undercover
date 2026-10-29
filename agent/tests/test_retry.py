import asyncio

import httpx2 as httpx
import openai
import pytest
from langchain.agents import create_agent
from langchain_core.exceptions import ModelAuthenticationError, ModelRateLimitError
from langchain_core.messages import AIMessage
from pydantic import Field

from agent.retry import middleware, transient
from agent.tests.test_agent import StubModel


class FailingModel(StubModel):
    failures: int
    calls: int = 0
    error: Exception = Field(exclude=True)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.parametrize(("failures", "expected"), [(1, 2), (3, 2)])
def test_transient_model_step_has_at_most_two_calls(failures, expected):
    model = FailingModel(
        responses=[AIMessage(content="Recovered")],
        failures=failures,
        error=TimeoutError(),
    )
    agent = create_agent(model, tools=[], middleware=[middleware()])
    if failures == 1:
        result = asyncio.run(
            agent.ainvoke({"messages": [{"role": "user", "content": "Go"}]})
        )
        assert result["messages"][-1].content == "Recovered"
    else:
        with pytest.raises(TimeoutError):
            asyncio.run(
                agent.ainvoke({"messages": [{"role": "user", "content": "Go"}]})
            )
    assert model.calls == expected


def test_auth_and_validation_are_not_retried():
    model = FailingModel(
        responses=[AIMessage(content="Unused")],
        failures=3,
        error=ValueError("validation"),
    )
    agent = create_agent(model, tools=[], middleware=[middleware()])
    with pytest.raises(ValueError, match="validation"):
        asyncio.run(agent.ainvoke({"messages": [{"role": "user", "content": "Go"}]}))
    assert model.calls == 1
    request = httpx.Request("POST", "https://provider.test")
    for status in (401, 403, 422, 429, 500, 503):
        error = openai.APIStatusError(
            "synthetic", response=httpx.Response(status, request=request), body=None
        )
        assert transient(error) == (status >= 500 or status == 429)
    assert transient(ModelRateLimitError("rate limited"))
    assert not transient(ModelAuthenticationError("auth failed"))
