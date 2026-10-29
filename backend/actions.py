"""Transactional decisions, handler sign-off and simulated payments."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException

from backend.db import Connection, Row, connect
from backend.models import (
    DecisionInput,
    DecisionRecord,
    PaymentInput,
    PaymentRecord,
    SignOffInput,
    SignOffRecord,
)
from backend.queries import required, setting


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


def approval_limit(connection: Connection) -> Decimal:
    """Read the operational sign-off threshold without manual handling rules."""
    return Decimal(str(setting(connection, "company")["payout_approval_limit"]))


def decide(claim_id: str, request: DecisionInput) -> DecisionRecord:
    """Save one immutable decision from the claim's active, unexpired run."""
    with connect() as connection:
        claim = lock_claim(connection, claim_id)
        run = connection.execute(
            "SELECT * FROM runs WHERE id = %s AND claim_id = %s",
            (request.run_id, claim_id),
        ).fetchone()
        if (
            claim["state"] != "in_progress"
            or not run
            or run["state"] != "running"
            or run["deadline"] <= datetime.now(UTC)
        ):
            raise HTTPException(409, "Only the active, unexpired claim run can decide.")
        if connection.execute(
            "SELECT claim_id FROM decisions WHERE claim_id = %s", (claim_id,)
        ).fetchone():
            raise HTTPException(409, "The claim already has a decision.")
        wording = setting(connection, "wording")["text"]
        if f"## {request.policy_section}. " not in wording:
            raise HTTPException(422, "The cited policy section does not exist.")
        state = "decided"
        if request.outcome == "approve" and request.payout > approval_limit(connection):
            state = "waiting_for_sign_off"
        row = connection.execute(
            "INSERT INTO decisions "
            "(claim_id, run_id, outcome, payout, explanation, "
            "policy_section, manual_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                claim_id,
                request.run_id,
                request.outcome,
                request.payout,
                request.explanation,
                request.policy_section,
                setting(connection, "manual_version")["version"],
            ),
        ).fetchone()
        connection.execute(
            "UPDATE claims SET state = %s WHERE id = %s", (state, claim_id)
        )
        activity(
            connection,
            claim_id,
            request.run_id,
            "decision",
            f"Decision recorded: {request.outcome}, ${request.payout:,.2f}; "
            f"policy section {request.policy_section}.",
        )
        return DecisionRecord.model_validate(row)


def sign_off(claim_id: str, request: SignOffInput) -> SignOffRecord:
    """Record eligible handler sign-off for the immutable approved payout."""
    with connect() as connection:
        lock_claim(connection, claim_id)
        decision = required(
            connection.execute(
                "SELECT * FROM decisions WHERE claim_id = %s", (claim_id,)
            ).fetchone(),
            "Decision",
        )
        if decision["outcome"] != "approve" or decision["payout"] <= approval_limit(
            connection
        ):
            raise HTTPException(409, "This decision does not require sign-off.")
        handler = required(
            connection.execute(
                "SELECT * FROM handlers WHERE id = %s", (request.handler_id,)
            ).fetchone(),
            "Handler",
        )
        if not handler["can_sign_off"]:
            raise HTTPException(403, "This handler cannot sign off over-limit payouts.")
        row = connection.execute(
            "INSERT INTO sign_offs (claim_id, handler_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING RETURNING *",
            (claim_id, request.handler_id),
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE claims SET state = 'decided' WHERE id = %s", (claim_id,)
            )
            activity(
                connection,
                claim_id,
                decision["run_id"],
                "sign_off",
                f"{handler['payload']['name']} signed off the approved payout.",
            )
        else:
            row = required(
                connection.execute(
                    "SELECT * FROM sign_offs WHERE claim_id = %s", (claim_id,)
                ).fetchone(),
                "Sign-off",
            )
            if row["handler_id"] != request.handler_id:
                raise HTTPException(409, "A different handler already signed off.")
        return SignOffRecord.model_validate(
            {**row, "handler_name": handler["payload"]["name"]}
        )


def pay(claim_id: str, request: PaymentInput) -> PaymentRecord:
    """Simulate the full approved payment after enforcing handler sign-off."""
    with connect() as connection:
        lock_claim(connection, claim_id)
        decision = connection.execute(
            "SELECT * FROM decisions WHERE claim_id = %s", (claim_id,)
        ).fetchone()
        if not decision or decision["outcome"] != "approve" or decision["payout"] <= 0:
            raise HTTPException(409, "A positive approved payout is required.")
        if request.amount != decision["payout"]:
            raise HTTPException(409, "Payment must equal the full approved payout.")
        signed = connection.execute(
            "SELECT * FROM sign_offs WHERE claim_id = %s", (claim_id,)
        ).fetchone()
        if decision["payout"] > approval_limit(connection) and not signed:
            raise HTTPException(409, "A handler must sign off before payment.")
        row = connection.execute(
            "INSERT INTO payments (claim_id, amount) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING RETURNING *",
            (claim_id, request.amount),
        ).fetchone()
        if row:
            activity(
                connection,
                claim_id,
                decision["run_id"],
                "payment",
                f"Simulated payment recorded: ${request.amount:,.2f}.",
            )
        else:
            row = connection.execute(
                "SELECT * FROM payments WHERE claim_id = %s", (claim_id,)
            ).fetchone()
        return PaymentRecord.model_validate(row)
