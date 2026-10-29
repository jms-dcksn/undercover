import asyncio

import pytest
from langchain_core.messages import AIMessage
from pydantic import Field

from agent import main, queue
from agent.tests.test_agent import StubModel, reply, scripted_model
from backend import coordinator, db, queue_runs, runs
from backend.models import QueueRunInput


class CapturingModel(StubModel):
    inputs: list = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.inputs.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def parent_model(ids):
    tasks = [
        {"claim_id": claim_id, "description": "Assess claim", "state": "todo"}
        for claim_id in ids
    ]
    messages = [
        reply("list_queue", {}, "list"),
        reply("write_todos", {"tasks": tasks}, "plan"),
    ]
    messages.extend(
        reply("work_claim", {"claim_id": claim_id}, f"work-{index}")
        for index, claim_id in enumerate(ids)
    )
    messages.extend(
        [
            reply("reconcile", {}, "check"),
            reply("complete_run", {}, "finish"),
            AIMessage(content="Untrusted final model text"),
        ]
    )
    return CapturingModel(responses=[*messages])


@pytest.mark.parametrize("limit", [5, 100, None])
def test_agent_selects_order_and_isolates_fresh_workers(
    limit, database, http_backend, monkeypatch
):
    with db.connect() as connection:
        connection.execute(
            "UPDATE claims SET payload = jsonb_set(payload, '{story}', "
            "'\"PRIVATE CHILD EVIDENCE\"')"
        )
    parent = queue_runs.start(
        QueueRunInput(thread_id="queue", claim_limit=limit, claim_id=None)
    )
    count = min(limit or 25, 25)
    ids = list(reversed(parent.snapshot))[:count]
    llm = parent_model(ids)
    workers = []

    async def child(claim_id, thread_id):
        scripted = scripted_model("decline", "0.00", False)
        model = CapturingModel(responses=scripted.responses)
        workers.append((claim_id, model))
        return await main.arun(claim_id, thread_id, model)

    monkeypatch.setattr(runs, "arun", child)
    assert asyncio.run(queue.arun(parent.id, llm)) == "Untrusted final model text"
    saved = queue_runs.get(parent.id)
    assert saved.state == "completed"
    assert [task.claim_id for task in saved.tasks] == ids
    assert [claim_id for claim_id, _ in workers] == ids
    assert all(task.state == "done" for task in saved.tasks)
    assert f"{count} decisions" in (saved.summary or "")
    with db.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM claims WHERE state = 'waiting'"
        ).fetchone() == {"n": 25 - count}
    parent_context = "\n".join(
        str(message.content) for step in llm.inputs for message in step
    )
    assert "PRIVATE CHILD EVIDENCE" not in parent_context
    assert "manual" not in parent_context
    for claim_id, model in workers:
        assert len(model.inputs[0]) == 2
        assert model.inputs[0][1].content == f"Decide claim {claim_id}."
        assert "PRIVATE CHILD EVIDENCE" in str(model.inputs[-1])
        assert claim_id in next(
            task.result for task in saved.tasks if task.claim_id == claim_id
        )


def test_empty_and_named_queue_agents(database, http_backend, monkeypatch):
    parent = queue_runs.start(
        QueueRunInput(thread_id="named", claim_limit=None, claim_id="CLM-1003")
    )

    async def child(claim_id, thread_id):
        return await main.arun(
            claim_id, thread_id, scripted_model("refer", "0.00", False)
        )

    monkeypatch.setattr(runs, "arun", child)
    asyncio.run(queue.arun(parent.id, parent_model(parent.snapshot)))
    assert queue_runs.get(parent.id).tasks[0].state == "left_for_handler"
    with db.connect() as connection:
        connection.execute("UPDATE claims SET state = 'decided'")
    empty = queue_runs.start(
        QueueRunInput(thread_id="empty", claim_limit=None, claim_id=None)
    )
    asyncio.run(queue.arun(empty.id, parent_model([])))
    assert "0 claims handled" in (queue_runs.get(empty.id).summary or "")


def test_coordinator_final_text_cannot_finish_missing_work(database, monkeypatch):
    parent = queue_runs.start(
        QueueRunInput(thread_id="miss", claim_limit=1, claim_id=None)
    )

    async def omit(run_id):
        return "All done"

    monkeypatch.setattr(coordinator, "arun", omit)
    asyncio.run(coordinator.execute(parent))
    saved = queue_runs.get(parent.id)
    assert saved.state == "failed"
    assert "Coordinator failed" in (saved.error or "")
