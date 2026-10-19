"""Read the claims queue and its supporting records."""

from decimal import Decimal

from fastapi import HTTPException

from backend.db import Connection, Row, connect
from backend.models import ClaimDetail, ClaimSummary, Handler

SUMMARY_SQL = """
    SELECT c.*, cu.payload->>'name' AS customer_name, p.plan,
           d.outcome, d.payout, pm.claim_id AS paid
    FROM claims c
    JOIN customers cu ON cu.id = c.customer_id
    JOIN policies p ON p.id = c.policy_id
    LEFT JOIN decisions d ON d.claim_id = c.id
    LEFT JOIN payments pm ON pm.claim_id = c.id
"""


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


def summary(claim: Row) -> ClaimSummary:
    """Combine queue, decision and payment state without conflating them."""
    status = "not_due"
    if claim["outcome"] == "approve" and claim["payout"] > 0:
        status = "paid" if claim["paid"] else "pending"
        if claim["state"] == "waiting_for_sign_off":
            status = "blocked"
    return ClaimSummary.model_validate(
        {
            "claim_id": claim["id"],
            "customer_name": claim["customer_name"],
            "plan": claim["plan"],
            "claim_type": claim["payload"]["claim_type"],
            "summary": claim["payload"]["summary"],
            "amount_claimed": Decimal(str(claim["payload"]["amount_claimed"])),
            "state": claim["state"],
            "outcome": claim["outcome"],
            "payout": claim["payout"],
            "payment_status": status,
        }
    )


def queue() -> list[ClaimSummary]:
    """Read the seeded queue in claim identifier order."""
    with connect() as connection:
        return [
            summary(claim)
            for claim in connection.execute(SUMMARY_SQL + " ORDER BY c.id").fetchall()
        ]


def detail(claim_id: str) -> ClaimDetail:
    """Read a complete claim and its linked business records."""
    with connect() as connection:
        claim = required(
            connection.execute(
                SUMMARY_SQL + " WHERE c.id = %s", (claim_id,)
            ).fetchone(),
            "Claim",
        )
        policy = required(
            connection.execute(
                "SELECT payload FROM policies WHERE id = %s", (claim["policy_id"],)
            ).fetchone(),
            "Policy",
        )["payload"]
        plan = required(
            connection.execute(
                "SELECT payload FROM plans WHERE id = %s", (policy["plan"],)
            ).fetchone(),
            "Plan",
        )["payload"]
        customer = required(
            connection.execute(
                "SELECT payload FROM customers WHERE id = %s", (claim["customer_id"],)
            ).fetchone(),
            "Customer",
        )["payload"]
        decision = connection.execute(
            "SELECT * FROM decisions WHERE claim_id = %s", (claim_id,)
        ).fetchone()
        sign_off = connection.execute(
            "SELECT s.*, h.payload->>'name' AS handler_name FROM sign_offs s "
            "JOIN handlers h ON s.handler_id = h.id WHERE claim_id = %s",
            (claim_id,),
        ).fetchone()
        payment = connection.execute(
            "SELECT * FROM payments WHERE claim_id = %s", (claim_id,)
        ).fetchone()
        return ClaimDetail.model_validate(
            {
                "summary": summary(claim),
                "claim": claim["payload"],
                "policy": policy,
                "plan": plan,
                "plan_terms": setting(connection, "plan_terms"),
                "customer": customer,
                "decision": decision,
                "sign_off": sign_off,
                "payment": payment,
            }
        )


def handlers() -> list[Handler]:
    """Read handler names and their sign-off eligibility."""
    with connect() as connection:
        return [
            Handler.model_validate(row["payload"])
            for row in connection.execute(
                "SELECT payload FROM handlers ORDER BY id"
            ).fetchall()
        ]
