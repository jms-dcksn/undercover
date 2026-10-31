"""Execute a bounded claim agent, then finalize its stored attempt."""

import asyncio
import logging
from datetime import UTC, datetime

from agent.main import arun
from backend import runs
from backend.models import RunRecord
from backend.queue_runs import ATTEMPT_SECONDS

TIMEOUT_SECONDS = ATTEMPT_SECONDS
logger = logging.getLogger(__name__)


async def execute(run: RunRecord) -> None:
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
