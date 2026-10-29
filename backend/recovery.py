"""Single-process interruption cleanup; never resumes a model conversation."""

import asyncio
import logging
from uuid import UUID

import psycopg

from backend import queue_runs, runs
from backend.db import DatabaseNotConfigured, connect
from backend.models import RunRecord

logger = logging.getLogger(__name__)
pending: dict[UUID, str] = {}
INTERVAL_SECONDS = 1


def fail_parent(run_id: UUID, error: str) -> None:
    """Release ownership and reconcile every active attempt atomically."""
    pending[run_id] = error
    with connect() as connection:
        parent = queue_runs.read_row(connection, run_id)
        if parent["state"] == "running":
            attempts = connection.execute(
                "SELECT * FROM runs WHERE parent_id = %s AND state = 'running'",
                (run_id,),
            ).fetchall()
            for row in attempts:
                runs.finish_in(connection, RunRecord.model_validate(row), error)
            connection.execute(
                "UPDATE queue_runs SET state = 'failed', error = %s, "
                "finished_at = now() WHERE id = %s",
                (error, run_id),
            )
    pending.pop(run_id, None)


def recover_all(interrupted: bool) -> None:
    """Recover interrupted/expired parents and pilot attempts without parent records."""
    with connect() as connection:
        parents = connection.execute(
            "SELECT id FROM queue_runs WHERE state = 'running' "
            "AND (%s OR deadline <= now())",
            (interrupted,),
        ).fetchall()
        attempts = connection.execute(
            "SELECT * FROM runs WHERE state = 'running' AND parent_id IS NULL "
            "AND (%s OR deadline <= now())",
            (interrupted,),
        ).fetchall()
    error = (
        "Backend interrupted; start a new run."
        if interrupted
        else "Run deadline exceeded."
    )
    for row in parents:
        fail_parent(row["id"], error)
    for row in attempts:
        runs.finish(RunRecord.model_validate(row), error)
    for run_id, message in list(pending.items()):
        fail_parent(run_id, message)


async def watchdog() -> None:
    """Retry failed storage cleanup and expire abandoned work while the API runs."""
    interrupted = False
    while True:
        try:
            await asyncio.to_thread(recover_all, interrupted)
            interrupted = False
        except (psycopg.Error, DatabaseNotConfigured):
            logger.exception(
                "Run cleanup unavailable; will retry when storage returns."
            )
        await asyncio.sleep(INTERVAL_SECONDS)
