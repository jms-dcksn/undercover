"""Single-process agent runs and their observable activity."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException

from agent.main import arun
from backend.actions import activity, lock_claim
from backend.db import connect
from backend.models import ActivityInput, ActivityRecord, RunRecord
from backend.queries import required

TIMEOUT_SECONDS = 120
logger = logging.getLogger(__name__)


def start(claim_id: str, thread_id: str) -> RunRecord:
    """Atomically reserve one waiting claim for an agent run."""
    with connect() as connection:
        claim = lock_claim(connection, claim_id)
        if claim["state"] != "waiting":
            raise HTTPException(409, "Only a waiting claim can be started.")
        row = connection.execute(
            "INSERT INTO runs (id, claim_id, thread_id, state, deadline) "
            "VALUES (%s, %s, %s, 'running', %s) RETURNING *",
            (
                uuid4(),
                claim_id,
                thread_id,
                datetime.now(UTC) + timedelta(seconds=TIMEOUT_SECONDS),
            ),
        ).fetchone()
        run = RunRecord.model_validate(row)
        connection.execute(
            "UPDATE claims SET state = 'in_progress' WHERE id = %s", (claim_id,)
        )
        activity(connection, claim_id, run.id, "started", "Agent run started.")
        return run


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
        if error is None and claim["state"] == "in_progress":
            error = "The agent finished without recording a decision. Retry the claim."
        state = "failed" if error else "completed"
        connection.execute(
            "UPDATE runs SET state = %s, finished_at = now() WHERE id = %s",
            (state, run.id),
        )
        if error and claim["state"] == "in_progress":
            connection.execute(
                "UPDATE claims SET state = 'waiting' WHERE id = %s", (run.claim_id,)
            )
        activity(
            connection, run.claim_id, run.id, state, error or "Agent run completed."
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
