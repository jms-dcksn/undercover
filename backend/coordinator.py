"""Bound the queue conversation; business outcomes live in Postgres."""

import asyncio
import logging
from datetime import UTC, datetime

from agent.queue import arun
from backend import queue_runs
from backend.db import connect
from backend.models import QueueRunRecord

logger = logging.getLogger(__name__)


async def execute(parent: QueueRunRecord) -> None:
    """Execute queue planning and reject a final message that omits work."""
    try:
        async with asyncio.timeout(
            max(0, (parent.deadline - datetime.now(UTC)).total_seconds())
        ):
            await arun(parent.id)
            saved = await asyncio.to_thread(queue_runs.get, parent.id)
            if saved.state == "running":
                await asyncio.to_thread(queue_runs.complete, parent.id)
    except Exception as error:
        logger.exception("Queue run %s failed", parent.id)
        with connect() as connection:
            connection.execute(
                "UPDATE queue_runs SET state = 'failed', error = %s, "
                "finished_at = now() "
                "WHERE id = %s AND state = 'running'",
                (
                    f"Coordinator failed ({type(error).__name__}). Check server log.",
                    parent.id,
                ),
            )
