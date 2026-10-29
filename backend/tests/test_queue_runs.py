from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import actions, coordinator, db, manage, queue_runs, runs
from backend.main import app
from backend.models import (
    DecisionInput,
    Outcome,
    QueueRunInput,
    RunRecord,
    TaskInput,
    TasksInput,
)

client = TestClient(app)


def parent(limit=None, claim_id=None):
    return queue_runs.start(
        QueueRunInput(thread_id=str(uuid4()), claim_limit=limit, claim_id=claim_id)
    )


def plan(run, ids):
    return queue_runs.write_tasks(
        run.id,
        TasksInput(
            tasks=[
                TaskInput(claim_id=claim_id, description="Assess claim", state="todo")
                for claim_id in ids
            ]
        ),
    )


def decide(attempt, outcome: Outcome = "decline", payout="0"):
    actions.decide(
        attempt.claim_id,
        DecisionInput(
            run_id=attempt.id,
            outcome=outcome,
            payout=Decimal(payout),
            explanation="The synthetic loss is excluded. Section 9 applies.",
            policy_section=9,
        ),
    )
    runs.finish(attempt, None)


def test_scope_contract_and_global_ownership(database, monkeypatch):
    async def no_model(parent):
        return None

    monkeypatch.setattr(coordinator, "execute", no_model)
    assert queue_runs.latest() is None
    assert client.get(f"/api/agent/runs/{uuid4()}").status_code == 404
    for limit in (0, -1, 1.5, True):
        assert (
            client.post(
                "/api/agent/runs",
                json={"thread_id": "test", "claim_limit": limit, "claim_id": None},
            ).status_code
            == 422
        )
    assert (
        client.post(
            "/api/agent/runs",
            json={"thread_id": "test", "claim_limit": None, "claim_id": "missing"},
        ).status_code
        == 404
    )
    response = client.post(
        "/api/agent/runs",
        json={"thread_id": "test", "claim_limit": 5, "claim_id": None},
    )
    assert response.status_code == 202
    saved = response.json()
    assert saved["mode"] == "queue"
    assert saved["claim_limit"] == 5
    assert len(saved["snapshot"]) == 25
    assert client.get("/api/agent/runs/latest").json() == saved
    with pytest.raises(HTTPException) as conflict:
        runs.start("CLM-1002", "named")
    assert conflict.value.status_code == 409


def test_tasks_admission_reconciliation_and_outcomes(database):
    run = parent(2)
    ids = run.snapshot[:3]
    plan(run, ids)
    with pytest.raises(HTTPException):
        plan(run, [ids[0], ids[0]])
    with pytest.raises(HTTPException):
        plan(run, ["missing"])
    with pytest.raises(HTTPException):
        queue_runs.write_tasks(
            run.id,
            TasksInput(
                tasks=[
                    TaskInput(
                        claim_id=ids[0], state="done", description="False completion"
                    )
                ]
            ),
        )
    attempt = queue_runs.delegate(run.id, ids[0])
    assert queue_runs.get(run.id).tasks[0].state == "in_progress"
    with pytest.raises(HTTPException):
        plan(run, ids[1:])
    with pytest.raises(HTTPException):
        queue_runs.delegate(run.id, ids[1])
    decide(attempt)
    second = queue_runs.delegate(run.id, ids[1])
    decide(second, "refer")
    with pytest.raises(HTTPException):
        queue_runs.delegate(run.id, ids[2])
    states = [task.state for task in queue_runs.get(run.id).tasks]
    assert states == ["done", "left_for_handler", "todo"]
    result = queue_runs.reconcile(run.id)
    assert result.ready
    assert result.outside_cap == 23
    finished = queue_runs.complete(run.id)
    assert finished.state == "completed"
    assert "2 decisions" in (finished.summary or "")
    assert client.get(f"/api/agent/runs/{run.id}").status_code == 200
    with pytest.raises(HTTPException):
        plan(run, ids)


def test_parallel_admission_and_retry_uses_one_slot(database):
    run = parent(1)
    plan(run, run.snapshot[:2])

    def delegate(claim_id):
        try:
            return queue_runs.delegate(run.id, claim_id)
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(delegate, [run.snapshot[0]] * 2 + [run.snapshot[1]]))
    attempts = [result for result in results if isinstance(result, RunRecord)]
    assert len(attempts) == 1
    attempt = attempts[0]
    runs.finish(attempt, "Synthetic failure")
    assert queue_runs.reconcile(run.id).retry == [attempt.claim_id]
    with pytest.raises(HTTPException):
        queue_runs.complete(run.id)
    retry = queue_runs.delegate(run.id, attempt.claim_id)
    assert retry.id != attempt.id
    decide(retry)
    assert queue_runs.reconcile(run.id).ready
    assert len([task for task in queue_runs.get(run.id).tasks if task.admitted]) == 1


def test_empty_named_and_uncapped(database):
    run = parent(claim_id="CLM-1001")
    assert run.mode == "named"
    assert run.snapshot == ["CLM-1001"]
    with db.connect() as connection:
        connection.execute("UPDATE queue_runs SET state = 'failed'")
        connection.execute("UPDATE claims SET state = 'decided'")
    empty = parent()
    assert empty.snapshot == []
    assert "0 claims handled" in (queue_runs.complete(empty.id).summary or "")


def test_additive_initialization_preserves_business_records(claim_run):
    actions.decide(
        "TEST-CLAIM",
        DecisionInput(
            run_id=claim_run,
            outcome="approve",
            payout=Decimal("1000"),
            explanation="Covered loss. Eligible expenses total $1000.",
            policy_section=3,
        ),
    )
    actions.pay("TEST-CLAIM", actions.PaymentInput(amount=Decimal("1000")))
    with db.connect() as connection:
        connection.execute("UPDATE decisions SET manual_version = NULL")
    before = client.get("/api/claims/TEST-CLAIM").json()
    events = runs.events("TEST-CLAIM")
    with db.connect() as connection:
        connection.execute(
            "DROP TABLE section_reads, document_sections, tasks, queue_runs CASCADE"
        )
        connection.execute("ALTER TABLE runs DROP COLUMN parent_id, DROP COLUMN error")
        connection.execute("ALTER TABLE decisions DROP COLUMN manual_version")
        connection.execute(
            "ALTER TABLE claims DROP COLUMN failures, DROP COLUMN last_error, "
            "DROP CONSTRAINT claims_state_check"
        )
        connection.execute(
            "ALTER TABLE claims ADD CONSTRAINT claims_state_check "
            "CHECK (state IN ('waiting', 'in_progress', "
            "'waiting_for_sign_off', 'decided'))"
        )
    manage.initialize()
    manage.initialize()
    assert client.get("/api/claims/TEST-CLAIM").json() == before
    assert runs.events("TEST-CLAIM") == events
    with db.connect() as connection:
        assert connection.execute(
            "SELECT count(*) AS n FROM pg_tables WHERE schemaname = 'undercover' "
            "AND NOT rowsecurity"
        ).fetchone() == {"n": 0}
