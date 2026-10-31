"""Single-process agent runs and their observable activity."""

from uuid import UUID

from backend import queue_runs
from backend.actions import approval_limit, pay_in
from backend.db import Connection, connect
from backend.models import (
    ActivityInput,
    ActivityRecord,
    PaymentInput,
    QueueRunInput,
    RunRecord,
    TaskInput,
    TasksInput,
)
from backend.records import active_run, activity, lock_claim, required


def start(claim_id: str, thread_id: str) -> RunRecord:
    """Atomically reserve one waiting claim for an agent run."""
    parent = queue_runs.start(
        QueueRunInput(thread_id=thread_id, claim_limit=None, claim_id=claim_id),
        legacy=True,
    )
    queue_runs.write_tasks(
        parent.id,
        TasksInput(
            tasks=[
                TaskInput(
                    claim_id=claim_id, description="Work named claim", state="todo"
                )
            ]
        ),
    )
    return queue_runs.delegate(parent.id, claim_id)


def current(claim_id: str) -> RunRecord:
    """Read the most recent run for a claim."""
    with connect() as connection:
        row = required(
            connection.execute(
                "SELECT * FROM runs WHERE claim_id = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (claim_id,),
            ).fetchone(),
            "Run",
        )
        return RunRecord.model_validate(row)


def events(claim_id: str) -> list[ActivityRecord]:
    """Read activity in committed sequence order."""
    with connect() as connection:
        required(
            connection.execute(
                "SELECT id FROM claims WHERE id = %s", (claim_id,)
            ).fetchone(),
            "Claim",
        )
        return [
            ActivityRecord.model_validate(row)
            for row in connection.execute(
                "SELECT * FROM activity WHERE claim_id = %s ORDER BY id", (claim_id,)
            ).fetchall()
        ]


def record_event(claim_id: str, run_id: UUID, request: ActivityInput) -> ActivityRecord:
    """Record tool activity only for the active, unexpired claim run."""
    with connect() as connection:
        lock_claim(connection, claim_id)
        active_run(connection, claim_id, run_id)
        row = connection.execute(
            "INSERT INTO activity (claim_id, run_id, kind, message) "
            "VALUES (%s, %s, %s, %s) RETURNING *",
            (claim_id, run_id, request.kind, request.message),
        ).fetchone()
        return ActivityRecord.model_validate(row)


def finish(run: RunRecord, error: str | None) -> None:
    """Finalize an attempt once, preserving committed business actions."""
    with connect() as connection:
        if run.parent_id:
            queue_runs.read_row(connection, run.parent_id)
        finish_in(connection, run, error)


def finish_in(connection: Connection, run: RunRecord, error: str | None) -> None:
    """Apply failure accounting and task reconciliation in one transaction."""
    claim = lock_claim(connection, run.claim_id)
    stored = required(
        connection.execute(
            "SELECT * FROM runs WHERE id = %s FOR UPDATE", (run.id,)
        ).fetchone(),
        "Run",
    )
    if stored["state"] != "running":
        return
    if error is None and claim["state"] == "in_progress":
        error = "The agent finished without recording a decision. Retry the claim."
    recover_payment(connection, run.claim_id)
    state = "failed" if error else "completed"
    connection.execute(
        "UPDATE runs SET state = %s, error = %s, finished_at = now() WHERE id = %s",
        (state, error, run.id),
    )
    if error and claim["state"] == "in_progress":
        connection.execute(
            "UPDATE claims SET failures = failures + 1, last_error = %s, "
            "state = CASE WHEN failures + 1 >= 2 THEN 'needs_handler' "
            "ELSE 'waiting' END WHERE id = %s",
            (error, run.claim_id),
        )
    activity(connection, run.claim_id, run.id, state, error or "Agent run completed.")
    if run.parent_id:
        task_state = queue_runs.terminal_state(connection, run.claim_id) or "todo"
        result = queue_runs.outcome_line(connection, run.claim_id)
        connection.execute(
            "UPDATE tasks SET state = %s, result = %s "
            "WHERE parent_id = %s AND claim_id = %s",
            (task_state, result, run.parent_id, run.claim_id),
        )


def recover_payment(connection: Connection, claim_id: str) -> None:
    """Recover a permitted unpaid approval without another model decision."""
    decision = connection.execute(
        "SELECT * FROM decisions WHERE claim_id = %s", (claim_id,)
    ).fetchone()
    if (
        decision
        and decision["outcome"] == "approve"
        and 0 < decision["payout"] <= approval_limit(connection)
    ):
        pay_in(connection, claim_id, PaymentInput(amount=decision["payout"]))
