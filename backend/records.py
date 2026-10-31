"""Shared transactional record access for claims and their attempts."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException

from backend.db import Connection, Row


def required(row: Row | None, label: str) -> Row:
    """Return a record or the API's standard not-found response."""
    if row is None:
        raise HTTPException(404, f"{label} not found.")
    return row


def setting(connection: Connection, key: str) -> Row:
    """Read one seeded application setting."""
    row = connection.execute(
        "SELECT payload FROM settings WHERE key = %s", (key,)
    ).fetchone()
    if row is None:
        raise HTTPException(503, "Database seed is missing. Run the documented setup.")
    return row["payload"]


def lock_claim(connection: Connection, claim_id: str) -> Row:
    """Serialize business state changes for one claim."""
    return required(
        connection.execute(
            "SELECT * FROM claims WHERE id = %s FOR UPDATE", (claim_id,)
        ).fetchone(),
        "Claim",
    )


def activity(
    connection: Connection, claim_id: str, run_id: UUID | None, kind: str, message: str
) -> None:
    """Record an observable action in the same transaction as its changes."""
    connection.execute(
        "INSERT INTO activity (claim_id, run_id, kind, message) "
        "VALUES (%s, %s, %s, %s)",
        (claim_id, run_id, kind, message),
    )


def active_run(connection: Connection, claim_id: str, run_id: UUID) -> Row:
    """Reject writes by expired, completed or replaced claim attempts."""
    run = connection.execute(
        "SELECT * FROM runs WHERE id = %s AND claim_id = %s", (run_id, claim_id)
    ).fetchone()
    if not run or run["state"] != "running" or run["deadline"] <= datetime.now(UTC):
        raise HTTPException(409, "This claim attempt is no longer active.")
    return run
