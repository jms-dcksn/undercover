"""Bound queue planning and recover once from stored tasks and short results."""

import asyncio
import logging
from datetime import UTC, datetime

import psycopg

import telemetry
from agent.queue import arun
from backend import queue_runs, recovery, worker
from backend.db import DatabaseNotConfigured
from backend.models import QueueRunRecord, RunRecord

logger = logging.getLogger(__name__)
COORDINATOR_ATTEMPTS = 2


async def fail(run_id, error: str) -> None:
    """Report storage failure honestly and let the watchdog retry cleanup."""
    try:
        await asyncio.to_thread(recovery.fail_parent, run_id, error)
    except (psycopg.Error, DatabaseNotConfigured):
        logger.exception("Failed run %s still needs storage cleanup.", run_id)


async def invoke(parent: QueueRunRecord) -> None:
    """Give the coordinator one fresh recovery invocation within the same budget."""
    for attempt in range(COORDINATOR_ATTEMPTS):
        try:
            await arun(parent.id)
            saved = await asyncio.to_thread(queue_runs.get, parent.id)
            if saved.state == "running":
                await asyncio.to_thread(queue_runs.complete, parent.id)
            return
        except Exception:
            saved = await asyncio.to_thread(queue_runs.get, parent.id)
            if saved.state == "completed":
                return
            if attempt + 1 == COORDINATOR_ATTEMPTS:
                raise
            logger.exception(
                "Reconstructing coordinator %s from saved tasks.", parent.id
            )


async def execute(parent: QueueRunRecord) -> None:
    """Trace the complete queue lifecycle, including recovery invocations."""
    with telemetry.observation(
        "process-queue", str(parent.id), {"run_id": str(parent.id)}
    ) as observation:
        await _execute(parent)
        if observation:
            saved = await asyncio.to_thread(queue_runs.get, parent.id)
            observation.update(
                output={"state": saved.state},
                level="ERROR" if saved.state == "failed" else "DEFAULT",
            )


async def _execute(parent: QueueRunRecord) -> None:
    """Execute bounded queue planning and clean up any unfinished ownership."""
    try:
        if parent.deadline <= datetime.now(UTC):
            raise TimeoutError("Queue deadline exceeded.")
        async with asyncio.timeout(
            max(0, (parent.deadline - datetime.now(UTC)).total_seconds())
        ):
            if parent.snapshot:
                await invoke(parent)
            else:
                await asyncio.to_thread(queue_runs.complete, parent.id)
    except asyncio.CancelledError:
        await fail(parent.id, "Backend interrupted; start a new run.")
        raise
    except Exception as error:
        logger.exception("Queue run %s failed", parent.id)
        await fail(
            parent.id, f"Coordinator failed ({type(error).__name__}). Check server log."
        )


async def execute_named(attempt: RunRecord) -> None:
    """Trace named work and its retries as one interaction."""
    with telemetry.observation(
        "process-named-claim",
        str(attempt.parent_id or attempt.id),
        {"run_id": str(attempt.parent_id or attempt.id)},
    ) as observation:
        await _execute_named(attempt)
        if observation and attempt.parent_id:
            saved = await asyncio.to_thread(queue_runs.get, attempt.parent_id)
            observation.update(
                output={"state": saved.state},
                level="ERROR" if saved.state == "failed" else "DEFAULT",
            )


async def _execute_named(attempt: RunRecord) -> None:
    """Retain the pilot named-claim entry point with automatic bounded retries."""
    if attempt.parent_id is None:
        raise ValueError("Named work requires a parent run.")
    try:
        await worker.execute(attempt)
        check = await asyncio.to_thread(queue_runs.reconcile, attempt.parent_id)
        if check.retry:
            retry = await asyncio.to_thread(
                queue_runs.delegate, attempt.parent_id, attempt.claim_id
            )
            await worker.execute(retry)
        await asyncio.to_thread(queue_runs.complete, attempt.parent_id)
    except asyncio.CancelledError:
        await fail(attempt.parent_id, "Backend interrupted; start a new run.")
        raise
    except Exception as error:
        await fail(attempt.parent_id, f"Named run failed ({type(error).__name__}).")
