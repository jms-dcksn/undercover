import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import actions, db, runs
from backend.main import app
from backend.models import DecisionInput

client = TestClient(app)


def test_duplicate_run_start(database):
    def start(_):
        try:
            return runs.start("CLM-1001", "test").state
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(start, range(2)))
    assert "running" in results
    assert 409 in results
    assert client.get("/api/claims/CLM-1001/run").status_code == 200
    assert client.get("/api/claims/missing/run").status_code == 404
    assert client.get("/api/claims/missing/activity").status_code == 404


def test_failed_run_returns_to_waiting_and_can_retry(database, monkeypatch):
    async def fail(claim_id, thread_id):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(runs, "arun", fail)
    run = runs.start("CLM-1001", "test")
    asyncio.run(runs.execute(run))
    run = runs.current("CLM-1001")
    assert run.state == "failed"
    assert client.get("/api/claims/CLM-1001").json()["summary"]["state"] == "waiting"
    events = runs.events("CLM-1001")
    assert [event.kind for event in events] == ["started", "failed"]
    assert "RuntimeError" in events[-1].message
    with db.connect() as connection:
        connection.execute("UPDATE queue_runs SET state = 'failed'")
    retry = runs.start("CLM-1001", "retry")
    assert retry.id != run.id
    assert (
        client.post(
            "/api/claims/CLM-1001/run", json={"thread_id": "duplicate"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("pay", [True, False])
def test_failure_preserves_committed_decision_and_payment(database, monkeypatch, pay):
    async def fail_after_decision(claim_id, thread_id):
        run = runs.current(claim_id)
        actions.decide(
            claim_id,
            DecisionInput(
                run_id=run.id,
                outcome="approve",
                payout=Decimal("420.00"),
                explanation="The delay is covered. Eligible expenses total $420.00.",
                policy_section=3,
            ),
        )
        if pay:
            actions.pay(claim_id, actions.PaymentInput(amount=Decimal("420.00")))
        raise RuntimeError("after commit")

    monkeypatch.setattr(runs, "arun", fail_after_decision)
    client.post("/api/claims/CLM-1001/run", json={"thread_id": "test"})
    detail = client.get("/api/claims/CLM-1001").json()
    assert detail["summary"]["state"] == "decided"
    assert detail["payment"] is not None
    assert detail["decision"]["payout"] == "420.00"
    assert runs.current("CLM-1001").state == "failed"


def test_timeout_and_missing_decision(database, monkeypatch):
    async def wait(claim_id, thread_id):
        await asyncio.Event().wait()

    monkeypatch.setattr(runs, "TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(runs, "arun", wait)
    run = runs.start("CLM-1001", "test")
    asyncio.run(runs.execute(run))
    assert "TimeoutError" in runs.events("CLM-1001")[-1].message

    async def no_decision(claim_id, thread_id):
        return "No action"

    monkeypatch.setattr(runs, "arun", no_decision)
    with db.connect() as connection:
        connection.execute("UPDATE queue_runs SET state = 'failed'")
    retry = runs.start("CLM-1001", "retry")
    asyncio.run(runs.execute(retry))
    assert "without recording a decision" in runs.events("CLM-1001")[-1].message


def test_activity_and_completed_run(database, monkeypatch):
    async def decide(claim_id, thread_id):
        run = runs.current(claim_id)
        event = client.post(
            f"/api/claims/{claim_id}/runs/{run.id}/activity",
            json={"kind": "tool_started", "message": "Read claim"},
        )
        assert event.status_code == 200
        actions.decide(
            claim_id,
            DecisionInput(
                run_id=run.id,
                outcome="refer",
                payout=Decimal("0.00"),
                explanation="A receipt is missing. Refer for more information.",
                policy_section=11,
            ),
        )
        return "Saved"

    monkeypatch.setattr(runs, "arun", decide)
    client.post("/api/claims/CLM-1001/run", json={"thread_id": "test"})
    run = runs.current("CLM-1001")
    assert run.state == "completed"
    event_path = f"/api/claims/CLM-1001/runs/{run.id}/activity"
    assert (
        client.post(
            event_path, json={"kind": "tool_finished", "message": "late"}
        ).status_code
        == 409
    )
    events = client.get("/api/claims/CLM-1001/activity").json()
    assert [event["id"] for event in events] == sorted(event["id"] for event in events)
    assert events[-1]["kind"] == "completed"
