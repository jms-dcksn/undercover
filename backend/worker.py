"""Execute a bounded claim agent, then finalize its stored attempt."""

import asyncio
import logging
from datetime import UTC, datetime

import telemetry
from agent.main import arun
from backend import runs
from backend.models import RunRecord
from backend.queue_runs import ATTEMPT_SECONDS

TIMEOUT_SECONDS = ATTEMPT_SECONDS
logger = logging.getLogger(__name__)


async def execute(run: RunRecord, traceparent: str | None = None) -> None:
    """Trace a background attempt under the coordinator that delegated it."""
    with telemetry.observation(
        "process-claim",
        str(run.parent_id or run.id),
        {"run_id": str(run.id), "claim_id": run.claim_id},
        traceparent,
    ) as observation:
        await _execute(run)
        if observation:
            saved = await asyncio.to_thread(runs.current, run.claim_id)
            observation.update(
                output={"state": saved.state},
                level="ERROR" if saved.state == "failed" else "DEFAULT",
            )


async def _execute(run: RunRecord) -> None:
    """Execute a bounded run without blocking the API event loop."""
    error = None
    try:
        async with asyncio.timeout(
            min(
                TIMEOUT_SECONDS,
                max(0, (run.deadline - datetime.now(UTC)).total_seconds()),
            )
        ):
            await arun(run.claim_id, run.thread_id)
    except Exception as exception:
        logger.exception("Agent run %s failed", run.id)
        error = f"Agent run failed ({type(exception).__name__}). Check the server log."
    await asyncio.to_thread(runs.finish, run, error)
