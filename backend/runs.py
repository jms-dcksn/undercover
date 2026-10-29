"""Single-process agent runs and their observable activity."""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException

from agent.main import arun
from backend import queue_runs
from backend.actions import activity, lock_claim
from backend.db import connect
from backend.models import (
    ActivityInput,
    ActivityRecord,
    QueueRunInput,
    RunRecord,
    TaskInput,
    TasksInput,
)
from backend.queries import required

TIMEOUT_SECONDS = 120
logger = logging.getLogger(__name__)


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
        run = connection.execute(
            "SELECT * FROM runs WHERE id = %s AND claim_id = %s", (run_id, claim_id)
        ).fetchone()
        if not run or run["state"] != "running" or run["deadline"] <= datetime.now(UTC):
            raise HTTPException(409, "This run is no longer active.")
        row = connection.execute(
            "INSERT INTO activity (claim_id, run_id, kind, message) "
            "VALUES (%s, %s, %s, %s) RETURNING *",
            (claim_id, run_id, request.kind, request.message),
        ).fetchone()
        return ActivityRecord.model_validate(row)


def finish(run: RunRecord, error: str | None) -> None:
    """Finish a run, preserving any decision and payment already committed."""
    with connect() as connection:
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
        state = "failed" if error else "completed"
        connection.execute(
            "UPDATE runs SET state = %s, error = %s, finished_at = now() WHERE id = %s",
            (state, error, run.id),
        )
        if error and claim["state"] == "in_progress":
            connection.execute(
                "UPDATE claims SET failures = failures + 1, last_error = %s, "
                "state = CASE WHEN failures + 1 >= 2 THEN 'needs_handler' "
                "ELSE 'waiting' END "
                "WHERE id = %s",
                (
                    error,
                    run.claim_id,
                ),
            )
        activity(
            connection, run.claim_id, run.id, state, error or "Agent run completed."
        )
        if run.parent_id:
            task_state = queue_runs.terminal_state(connection, run.claim_id) or "todo"
            result = error or f"{run.claim_id}: {task_state}"
            connection.execute(
                "UPDATE tasks SET state = %s, result = %s "
                "WHERE parent_id = %s AND claim_id = %s",
                (task_state, result, run.parent_id, run.claim_id),
            )
            connection.execute(
                "UPDATE queue_runs SET state = %s, error = %s, summary = %s, "
                "finished_at = now() WHERE id = %s AND legacy",
                (state, error, result, run.parent_id),
            )


async def execute(run: RunRecord) -> None:
    """Execute a bounded run without blocking the API event loop."""
    error = None
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            await arun(run.claim_id, run.thread_id)
    except Exception as exception:
        logger.exception("Agent run %s failed", run.id)
        error = f"Agent run failed ({type(exception).__name__}). Check the server log."
    await asyncio.to_thread(finish, run, error)
