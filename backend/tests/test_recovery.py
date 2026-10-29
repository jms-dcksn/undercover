import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent import main, queue
from agent.tests.test_agent import reply, scripted_model
from agent.tests.test_queue import CapturingModel
from backend import actions, coordinator, db, queue_runs, recovery, runs
from backend.main import app
from backend.models import DecisionInput
from backend.tests.test_queue_runs import parent, plan

client = TestClient(app)


def test_fail_retry_exhaustion_and_later_work(database, http_backend, monkeypatch):
    run = parent(3)
    ids = run.snapshot[:3]
    calls = {}
    workers = []

    async def child(claim_id, thread_id):
        calls[claim_id] = calls.get(claim_id, 0) + 1
        workers.append((claim_id, thread_id))
        if claim_id == ids[1] or (claim_id == ids[0] and calls[claim_id] == 1):
            raise RuntimeError("Synthetic failure")
        return await main.arun(
            claim_id, thread_id, scripted_model("decline", "0", False)
        )

    monkeypatch.setattr(runs, "arun", child)
    tasks = [
        {"claim_id": claim_id, "description": "Assess claim", "state": "todo"}
        for claim_id in ids
    ]
    order = [ids[0], ids[1], ids[0], ids[1], ids[2]]
    messages = [reply("write_todos", {"tasks": tasks}, "plan")]
    messages.extend(
        reply("work_claim", {"claim_id": claim_id}, str(index))
        for index, claim_id in enumerate(order)
    )
    messages.extend(
        [reply("reconcile", {}, "check"), reply("complete_run", {}, "complete")]
    )
    messages.append(AIMessage(content="Done"))
    asyncio.run(queue.arun(run.id, CapturingModel(responses=[*messages])))
    assert [claim_id for claim_id, _ in workers] == order
    assert len({thread for _, thread in workers}) == 5
    assert (
        client.get(f"/api/claims/{ids[1]}").json()["summary"]["state"]
        == "needs_handler"
    )
    assert client.get(f"/api/claims/{ids[1]}").json()["decision"] is None
    following = parent()
    assert ids[1] not in following.snapshot
    assert ids[0] not in following.snapshot


def test_reconciliation_catches_omission_and_first_failure(database):
    run = parent(2)
    plan(run, run.snapshot[:2])
    first = queue_runs.delegate(run.id, run.snapshot[0])
    assert queue_runs.reconcile(run.id).active == [first.claim_id]
    with pytest.raises(HTTPException):
        queue_runs.complete(run.id)
    runs.finish(first, "first failure")
    result = queue_runs.reconcile(run.id)
    assert result.retry == [first.claim_id]
    assert result.missing
    with pytest.raises(HTTPException):
        queue_runs.complete(run.id)


def test_cleanup_idempotent_cross_run_failure_count_and_late_writes(database):
    run = parent(1)
    plan(run, run.snapshot[:1])
    first = queue_runs.delegate(run.id, run.snapshot[0])
    recovery.recover_all(True)
    recovery.recover_all(True)
    assert queue_runs.get(run.id).state == "failed"
    assert (
        client.get(f"/api/claims/{first.claim_id}").json()["summary"]["state"]
        == "waiting"
    )
    second_parent = parent(1, claim_id=None)
    plan(second_parent, [first.claim_id])
    second = queue_runs.delegate(second_parent.id, first.claim_id)
    recovery.recover_all(True)
    assert (
        client.get(f"/api/claims/{first.claim_id}").json()["summary"]["state"]
        == "needs_handler"
    )
    with db.connect() as connection:
        assert connection.execute(
            "SELECT failures FROM claims WHERE id = %s", (first.claim_id,)
        ).fetchone() == {"failures": 2}
    body = {
        "run_id": str(second.id),
        "outcome": "decline",
        "payout": "0",
        "explanation": "Late write. Must fail.",
        "policy_section": 9,
    }
    assert (
        client.post(f"/api/claims/{first.claim_id}/decision", json=body).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/claims/{first.claim_id}/runs/{second.id}/payment",
            json={"amount": "10"},
        ).status_code
        == 409
    )


def test_cleanup_recovers_saved_payment_and_preserves_signoff_boundary(database):
    for amount in ("1000.00", "1000.01"):
        run = parent(1)
        claim_id = run.snapshot[0]
        plan(run, [claim_id])
        attempt = queue_runs.delegate(run.id, claim_id)
        actions.decide(
            claim_id,
            DecisionInput(
                run_id=attempt.id,
                outcome="approve",
                payout=Decimal(amount),
                explanation="Covered loss. Saved before interruption.",
                policy_section=3,
            ),
        )
        assert queue_runs.reconcile(run.id).active == [claim_id]
        recovery.recover_all(True)
        recovery.recover_all(True)
        detail = client.get(f"/api/claims/{claim_id}").json()
        assert (detail["payment"] is not None) == (amount == "1000.00")
        assert detail["decision"]["payout"] == amount
        with db.connect() as connection:
            assert connection.execute(
                "SELECT failures FROM claims WHERE id = %s", (claim_id,)
            ).fetchone() == {"failures": 0}


def test_coordinator_recovery_total_deadline_and_storage_outage(database, monkeypatch):
    run = parent(1)
    plan(run, run.snapshot[:1])
    attempt = queue_runs.delegate(run.id, run.snapshot[0])
    count = 0

    async def fail(run_id):
        nonlocal count
        count += 1
        raise RuntimeError("permanent coordinator error")

    monkeypatch.setattr(coordinator, "arun", fail)
    asyncio.run(coordinator.execute(run))
    assert count == 2
    assert runs.current(attempt.claim_id).state == "failed"
    assert queue_runs.get(run.id).state == "failed"
    other = parent(1)
    plan(other, other.snapshot[:1])
    queue_runs.delegate(other.id, other.snapshot[0])
    expired = other.model_copy(
        update={"deadline": datetime.now(UTC) - timedelta(seconds=1)}
    )
    asyncio.run(coordinator.execute(expired))
    assert "TimeoutError" in (queue_runs.get(other.id).error or "")
    third = parent(1)
    real_connect = recovery.connect

    def offline():
        raise psycopg.OperationalError("synthetic offline")

    monkeypatch.setattr(recovery, "connect", offline)
    asyncio.run(coordinator.fail(third.id, "Visible storage failure"))
    assert third.id in recovery.pending
    monkeypatch.setattr(recovery, "connect", real_connect)
    recovery.recover_all(False)
    assert queue_runs.get(third.id).error == "Visible storage failure"
    assert third.id not in recovery.pending


def test_actual_backend_restart_cleans_ownership(database):
    run = parent(1)
    plan(run, run.snapshot[:1])
    attempt = queue_runs.delegate(run.id, run.snapshot[0])
    with TestClient(app) as restarted:
        assert restarted.get(f"/api/agent/runs/{run.id}").json()["state"] == "failed"
        assert (
            restarted.get(f"/api/claims/{attempt.claim_id}").json()["summary"]["state"]
            == "waiting"
        )
    assert attempt.claim_id in parent().snapshot


def test_orphan_pilot_attempt_is_recovered(claim_run):
    recovery.recover_all(True)
    recovery.recover_all(True)
    assert runs.current("TEST-CLAIM").state == "failed"
    assert client.get("/api/claims/TEST-CLAIM").json()["summary"]["state"] == "waiting"
