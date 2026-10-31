import asyncio
import json
from functools import cache
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import telemetry
from agent import main, queue
from agent.tests.test_agent import StubModel, scripted_model
from agent.tests.test_queue import parent_model
from backend import coordinator, db, queue_runs, runs, worker
from backend.models import QueueRunInput


class TracedModel(StubModel):
    model_name: str = "synthetic-model"


@pytest.fixture
def tracing(monkeypatch):
    key = f"pk-lf-test-{uuid4()}"
    secret = f"sk-lf-test-{uuid4()}"
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", key)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", secret)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://localhost")
    monkeypatch.setenv("LANGFUSE_CAPTURE_CONTENT", "false")
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=key,
        secret_key=secret,
        base_url="http://localhost",
        environment="test",
        tracer_provider=TracerProvider(),
        span_exporter=exporter,
        mask_otel_spans=telemetry.mask_spans,
    )

    @cache
    def local_client():
        return client

    monkeypatch.setattr(telemetry, "_client", local_client)
    yield client, exporter
    client.shutdown()


def spans(tracing):
    client, exporter = tracing
    client.flush()
    return exporter.get_finished_spans()


def test_disabled_and_incomplete_configuration_do_not_initialize(monkeypatch):
    def unexpected_client():
        pytest.fail("Disabled tracing initialized a client")

    monkeypatch.setattr(telemetry, "_client", unexpected_client)
    assert telemetry.callbacks() == []
    with telemetry.observation("process-queue", "test", {}) as observation:
        assert observation is None
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert telemetry.callbacks() == []
    headers = {}
    telemetry.inject_headers(headers)
    assert headers == {}


def test_queue_trace_nests_http_workers_and_masks_content(
    database, http_backend, monkeypatch, tracing
):
    with db.connect() as connection:
        connection.execute(
            "UPDATE claims SET payload = jsonb_set(payload, '{story}', "
            "'\"SENSITIVE MEDICAL EVIDENCE\"')"
        )
    parent = queue_runs.start(
        QueueRunInput(thread_id="trace-test", claim_limit=1, claim_id=None)
    )

    async def child(claim_id, thread_id):
        model = TracedModel(
            responses=scripted_model("decline", "0.00", False).responses
        )
        for message in model.responses:
            assert isinstance(message, AIMessage)
            message.usage_metadata = {
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
            }
            message.response_metadata = {"model_name": "synthetic-model"}
        return await main.arun(claim_id, thread_id, model)

    async def parent_agent(run_id):
        return await queue.arun(run_id, parent_model(parent.snapshot[:1]))

    monkeypatch.setattr(worker, "arun", child)
    monkeypatch.setattr(coordinator, "arun", parent_agent)
    asyncio.run(coordinator.execute(parent))
    captured = spans(tracing)
    assert queue_runs.get(parent.id).state == "completed"
    assert len({span.context.trace_id for span in captured}) == 1
    roots = [span for span in captured if span.parent is None]
    assert [span.name for span in roots] == ["process-queue"]
    names = {span.name for span in captured}
    assert {"queue-agent", "claim-agent", "process-claim", "work_claim"} <= names
    by_id = {span.context.span_id: span for span in captured}
    child_span = next(span for span in captured if span.name == "process-claim")
    assert by_id[child_span.parent.span_id].name == "work_claim"
    for span in captured:
        assert span.attributes["session.id"] == str(parent.id)
    agents = [span for span in captured if span.name in {"queue-agent", "claim-agent"}]
    assert all(
        span.attributes["langfuse.observation.type"] == "agent" for span in agents
    )
    generations = [
        span
        for span in captured
        if span.attributes["langfuse.observation.type"] == "generation"
    ]
    assert generations
    assert any(
        span.attributes.get("langfuse.observation.model.name") == "synthetic-model"
        and json.loads(span.attributes["langfuse.observation.usage_details"])["input"]
        == 10
        for span in generations
    )
    assert json.loads(roots[0].attributes["langfuse.observation.output"]) == {
        "state": "completed"
    }
    attributes = repr([dict(span.attributes) for span in captured])
    assert "SENSITIVE MEDICAL EVIDENCE" not in attributes
    assert "Covered expenses" not in attributes
    assert all(not span.events for span in captured)


def test_error_and_cancellation_do_not_export_raw_exceptions(tracing):
    for error in (ValueError("PRIVATE ERROR"), asyncio.CancelledError("PRIVATE ERROR")):
        with (
            pytest.raises(type(error)),
            telemetry.observation("process-claim", "test", {}),
        ):
            raise error
    captured = spans(tracing)
    assert len(captured) == 2
    assert all(
        span.attributes["langfuse.observation.level"] == "ERROR" for span in captured
    )
    assert "PRIVATE ERROR" not in repr([dict(span.attributes) for span in captured])
    assert all(not span.events for span in captured)


def test_named_execution_records_saved_failure(
    database, http_backend, monkeypatch, tracing
):
    attempt = runs.start("CLM-1001", "trace-named")

    async def fail(claim_id, thread_id):
        raise ValueError("PRIVATE FAILURE")

    monkeypatch.setattr(worker, "arun", fail)
    asyncio.run(coordinator.execute_named(attempt))
    captured = spans(tracing)
    root = next(span for span in captured if span.name == "process-named-claim")
    workers = [span for span in captured if span.name == "process-claim"]
    assert len(workers) == 2
    assert all(
        span.attributes["langfuse.observation.level"] == "ERROR" for span in workers
    )
    assert root.attributes["session.id"] == str(attempt.parent_id)
    assert json.loads(workers[0].attributes["langfuse.observation.output"]) == {
        "state": "failed"
    }


def test_shutdown_only_drains_an_initialized_client(monkeypatch):
    telemetry._client.cache_clear()
    telemetry.flush()
    telemetry.shutdown()


def test_script_invocations_flush_without_closing_shared_client(
    claim_run, http_backend, tracing
):
    for _ in range(2):
        assert (
            main.run(
                "TEST-CLAIM",
                "test-thread",
                TracedModel(responses=[AIMessage(content="Done")]),
            )
            == "Done"
        )
    captured = tracing[1].get_finished_spans()
    assert sum(span.name == "process-claim" for span in captured) == 2
    assert sum(span.name == "claim-agent" for span in captured) == 2


@pytest.mark.parametrize("capture", ["true", "false"])
def test_client_applies_content_policy(monkeypatch, capture):
    options = []
    monkeypatch.setenv("LANGFUSE_CAPTURE_CONTENT", capture)
    monkeypatch.setattr(telemetry, "Langfuse", lambda **kwargs: options.append(kwargs))
    telemetry._client.cache_clear()
    telemetry._client()
    assert options[0]["environment"] == "development"
    assert options[0]["mask_otel_spans"] == (
        None if capture == "true" else telemetry.mask_spans
    )
    telemetry._client.cache_clear()
