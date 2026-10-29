"""Persist queue plans and serialize admission against authoritative claim state."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from backend.actions import activity, lock_claim
from backend.db import Connection, Row, connect
from backend.models import (
    QueueRunInput,
    QueueRunRecord,
    Reconciliation,
    RunRecord,
    TasksInput,
)
from backend.queries import required

ATTEMPT_SECONDS = 120
OVERHEAD_SECONDS = 60
MAX_FAILURES = 2


def read_row(connection: Connection, run_id: UUID, *, active: bool = False) -> Row:
    """Lock a parent before modifying its plan or admitting work."""
    row = required(
        connection.execute(
            "SELECT * FROM queue_runs WHERE id = %s FOR UPDATE", (run_id,)
        ).fetchone(),
        "Queue run",
    )
    if active and (row["state"] != "running" or row["deadline"] <= datetime.now(UTC)):
        raise HTTPException(409, "Queue run is no longer active.")
    return row


def record(connection: Connection, row: Row) -> QueueRunRecord:
    """Read the ordered tasks with a parent record."""
    tasks = connection.execute(
        "SELECT * FROM tasks WHERE parent_id = %s ORDER BY position", (row["id"],)
    ).fetchall()
    return QueueRunRecord.model_validate({**row, "tasks": tasks})


def get(run_id: UUID) -> QueueRunRecord:
    """Read a stored parent and its plan."""
    with connect() as connection:
        return record(connection, read_row(connection, run_id))


def latest() -> QueueRunRecord | None:
    """Retain the last terminal run until another starts."""
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM queue_runs ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return record(connection, row) if row else None


def start(request: QueueRunInput, *, legacy: bool = False) -> QueueRunRecord:
    """Snapshot eligible work and acquire the database-wide coordinator slot."""
    try:
        with connect() as connection:
            if request.claim_id:
                claim = lock_claim(connection, request.claim_id)
                if claim["state"] != "waiting":
                    raise HTTPException(409, "Only a waiting claim can be started.")
            rows = connection.execute(
                "SELECT c.id FROM claims c WHERE state = 'waiting' "
                "AND NOT EXISTS (SELECT 1 FROM decisions d WHERE d.claim_id = c.id) "
                "AND (%s::text IS NULL OR c.id = %s) ORDER BY c.id",
                (request.claim_id, request.claim_id),
            ).fetchall()
            snapshot = [row["id"] for row in rows]
            count = min(len(snapshot), request.claim_limit or len(snapshot))
            row = connection.execute(
                "INSERT INTO queue_runs "
                "(id, thread_id, mode, claim_id, claim_limit, snapshot, state, "
                "deadline, legacy) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING *",
                (
                    uuid4(),
                    request.thread_id,
                    "named" if request.claim_id else "queue",
                    request.claim_id,
                    request.claim_limit,
                    Jsonb(snapshot),
                    "running",
                    datetime.now(UTC)
                    + timedelta(seconds=OVERHEAD_SECONDS + count * ATTEMPT_SECONDS * 2),
                    legacy,
                ),
            ).fetchone()
            return record(connection, required(row, "Queue run"))
    except UniqueViolation as error:
        raise HTTPException(409, "Another queue or named run is active.") from error


def terminal_state(connection: Connection, claim_id: str) -> str | None:
    """Derive terminal task state from committed business outcomes."""
    row = required(
        connection.execute(
            "SELECT c.state, d.outcome, d.payout, p.claim_id AS paid "
            "FROM claims c LEFT JOIN decisions d ON c.id = d.claim_id "
            "LEFT JOIN payments p ON c.id = p.claim_id WHERE c.id = %s",
            (claim_id,),
        ).fetchone(),
        "Claim",
    )
    if (
        row["state"] in ("needs_handler", "waiting_for_sign_off")
        or row["outcome"] == "refer"
    ):
        return "left_for_handler"
    if row["outcome"]:
        if row["outcome"] == "approve" and row["payout"] > 0 and not row["paid"]:
            return "left_for_handler"
        return "done"
    return None


def write_tasks(run_id: UUID, request: TasksInput) -> QueueRunRecord:
    """Store the model's ordered plan without allowing invented outcomes."""
    ids = [task.claim_id for task in request.tasks]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Tasks must have unique claim IDs.")
    with connect() as connection:
        parent = read_row(connection, run_id, active=True)
        admitted = connection.execute(
            "SELECT claim_id FROM tasks WHERE parent_id = %s AND admitted", (run_id,)
        ).fetchall()
        if any(row["claim_id"] not in ids for row in admitted):
            raise HTTPException(409, "Admitted work cannot be deleted.")
        for position, task in enumerate(request.tasks):
            if task.claim_id not in parent["snapshot"]:
                raise HTTPException(422, "Task claim is outside this run snapshot.")
            validate_task(connection, run_id, task.claim_id, task.state)
            connection.execute(
                "INSERT INTO tasks (parent_id, claim_id, position, description, state) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (parent_id, claim_id) "
                "DO UPDATE SET position = EXCLUDED.position, "
                "description = EXCLUDED.description, state = EXCLUDED.state",
                (run_id, task.claim_id, position, task.description, task.state),
            )
        connection.execute(
            "DELETE FROM tasks WHERE parent_id = %s AND NOT (claim_id = ANY(%s))",
            (run_id, ids),
        )
        return record(connection, parent)


def validate_task(
    connection: Connection, parent_id: UUID, claim_id: str, state: str
) -> None:
    """Prevent plan edits from masking incomplete work."""
    terminal = terminal_state(connection, claim_id)
    active = connection.execute(
        "SELECT id FROM runs WHERE parent_id = %s AND claim_id = %s "
        "AND state = 'running'",
        (parent_id, claim_id),
    ).fetchone()
    if terminal and state != terminal:
        raise HTTPException(409, f"Recorded outcome requires {terminal}.")
    if not terminal and state in ("done", "left_for_handler"):
        raise HTTPException(409, "No recorded terminal outcome for this task.")
    if (state == "in_progress") != bool(active):
        raise HTTPException(409, "Task progress must match its active attempt.")


def delegate(run_id: UUID, claim_id: str) -> RunRecord:
    """Reserve one distinct cap slot and one fresh claim attempt atomically."""
    with connect() as connection:
        parent = read_row(connection, run_id, active=True)
        if claim_id not in parent["snapshot"]:
            raise HTTPException(409, "Claim is outside this run snapshot.")
        task = required(
            connection.execute(
                "SELECT * FROM tasks WHERE parent_id = %s AND claim_id = %s",
                (run_id, claim_id),
            ).fetchone(),
            "Planned task",
        )
        active = connection.execute(
            "SELECT id FROM runs WHERE parent_id = %s AND state = 'running'", (run_id,)
        ).fetchone()
        if active:
            raise HTTPException(409, "Wait for the active claim attempt first.")
        admitted = connection.execute(
            "SELECT count(*) AS n FROM tasks WHERE parent_id = %s AND admitted",
            (run_id,),
        ).fetchone()
        if (
            not task["admitted"]
            and parent["claim_limit"] is not None
            and admitted
            and admitted["n"] >= parent["claim_limit"]
        ):
            raise HTTPException(409, "Distinct claim cap reached.")
        claim = lock_claim(connection, claim_id)
        if claim["state"] != "waiting" or claim["failures"] >= MAX_FAILURES:
            raise HTTPException(409, "Claim is not eligible for another attempt.")
        row = connection.execute(
            "INSERT INTO runs (id, claim_id, thread_id, parent_id, state, deadline) "
            "VALUES (%s, %s, %s, %s, 'running', %s) RETURNING *",
            (
                uuid4(),
                claim_id,
                str(uuid4()),
                run_id,
                min(
                    parent["deadline"],
                    datetime.now(UTC) + timedelta(seconds=ATTEMPT_SECONDS),
                ),
            ),
        ).fetchone()
        attempt = RunRecord.model_validate(row)
        connection.execute(
            "UPDATE claims SET state = 'in_progress' WHERE id = %s", (claim_id,)
        )
        connection.execute(
            "UPDATE tasks SET admitted = true, state = 'in_progress' "
            "WHERE parent_id = %s AND claim_id = %s",
            (run_id, claim_id),
        )
        activity(
            connection, claim_id, attempt.id, "started", "Fresh claim attempt started."
        )
        return attempt


def reconcile_in(connection: Connection, parent: Row) -> Reconciliation:
    """Compare the immutable scope and cap with actual attempts and outcomes."""
    tasks = connection.execute(
        "SELECT t.*, c.state AS claim_state, EXISTS(SELECT 1 FROM runs r "
        "WHERE r.parent_id = t.parent_id AND r.claim_id = t.claim_id "
        "AND r.state = 'running') AS active_attempt FROM tasks t "
        "JOIN claims c ON c.id = t.claim_id "
        "WHERE parent_id = %s AND admitted ORDER BY position",
        (parent["id"],),
    ).fetchall()
    admitted = {task["claim_id"] for task in tasks}
    slots = max(0, (parent["claim_limit"] or len(parent["snapshot"])) - len(admitted))
    missing = [claim_id for claim_id in parent["snapshot"] if claim_id not in admitted]
    retry = [task["claim_id"] for task in tasks if task["claim_state"] == "waiting"]
    active = [task["claim_id"] for task in tasks if task["active_attempt"]]
    return Reconciliation(
        ready=not active and not retry and (not missing or slots == 0),
        missing=missing if slots else [],
        retry=retry,
        active=active,
        slots_remaining=slots,
        outside_cap=max(0, len(missing) - slots),
    )


def reconcile(run_id: UUID) -> Reconciliation:
    """Report missing work and retries without selecting a work order."""
    with connect() as connection:
        return reconcile_in(connection, read_row(connection, run_id, active=True))


def complete(run_id: UUID) -> QueueRunRecord:
    """Recheck scope and save a summary derived only from committed records."""
    with connect() as connection:
        parent = read_row(connection, run_id, active=True)
        result = reconcile_in(connection, parent)
        if not result.ready:
            raise HTTPException(409, result.model_dump())
        counts = connection.execute(
            "SELECT count(*) AS handled, "
            "count(*) FILTER (WHERE c.failures > 0) AS failures, "
            "count(*) FILTER (WHERE t.state = 'left_for_handler') AS handler, "
            "count(p.claim_id) AS payments, count(d.claim_id) AS decisions "
            "FROM tasks t "
            "JOIN claims c ON c.id = t.claim_id "
            "LEFT JOIN decisions d ON d.claim_id = c.id "
            "LEFT JOIN payments p ON p.claim_id = c.id "
            "WHERE parent_id = %s AND admitted",
            (run_id,),
        ).fetchone()
        counts = required(counts, "Counts")
        summary = (
            f"{counts['handled']} claims handled; {counts['decisions']} decisions; "
            f"{counts['payments']} payments; "
            f"{counts['failures']} claims with failures; "
            f"{counts['handler']} left for handler; {result.outside_cap} outside cap."
        )
        row = connection.execute(
            "UPDATE queue_runs SET state = 'completed', summary = %s, "
            "finished_at = now() "
            "WHERE id = %s RETURNING *",
            (summary, run_id),
        ).fetchone()
        return record(connection, required(row, "Queue run"))


def outcome_line(connection: Connection, claim_id: str) -> str:
    """Summarize saved state without copying evidence or model explanations."""
    row = required(
        connection.execute(
            "SELECT c.state, c.failures, c.last_error, d.outcome, d.payout, p.amount "
            "FROM claims c LEFT JOIN decisions d ON c.id = d.claim_id "
            "LEFT JOIN payments p ON p.claim_id = c.id WHERE c.id = %s",
            (claim_id,),
        ).fetchone(),
        "Claim",
    )
    if row["outcome"]:
        payment = "paid" if row["amount"] else "pending"
        if row["state"] == "waiting_for_sign_off":
            payment = "blocked for sign-off"
        if row["outcome"] != "approve" or row["payout"] == 0:
            payment = "not due"
        return f"{claim_id}: {row['outcome']} ${row['payout']:.2f}; payment {payment}."
    return (
        f"{claim_id}: technical failure {row['failures']}/2; "
        f"{row['state']}; {row['last_error']}"
    )
