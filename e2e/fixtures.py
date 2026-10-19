"""Synthetic browser-test claims, unrelated to the evaluation answer key."""

from psycopg.types.json import Jsonb

from backend.db import connect
from backend.manage import insert_records, seed

SCENARIOS = {
    "E2E-APPROVE": ("approve", "420.00"),
    "E2E-LIMIT": ("approve", "1000.00"),
    "E2E-OVER": ("approve", "1250.00"),
    "E2E-DECLINE": ("decline", "0.00"),
    "E2E-REFER": ("refer", "0.00"),
    "E2E-FAIL": ("refer", "0.00"),
}


def prepare() -> None:
    """Reset only the application schema in an explicitly marked test database."""
    with connect() as connection:
        purpose = connection.execute(
            "SELECT payload FROM settings WHERE key = 'purpose'"
        ).fetchone()
        if purpose != {"payload": {"value": "test"}}:
            raise RuntimeError("Run uv run -m backend.manage init-test first.")
        connection.execute(
            "TRUNCATE customers, plans, policies, handlers, claims, runs, "
            "decisions, sign_offs, payments, activity RESTART IDENTITY CASCADE"
        )
        connection.execute("DELETE FROM settings WHERE key != 'purpose'")
    seed()
    with connect() as connection:
        insert_records(
            connection,
            "customers",
            [
                {
                    "customer_id": "CUS-E2E",
                    "name": "Synthetic Traveler",
                    "previous_claims": [],
                }
            ],
            {"id": "customer_id"},
        )
        insert_records(
            connection,
            "policies",
            [
                {
                    "policy_id": "POL-E2E",
                    "customer_id": "CUS-E2E",
                    "plan": "first",
                    "add_ons": [],
                    "purchased_on": "2026-01-01",
                    "trip": {
                        "departs_on": "2026-06-01",
                        "returns_on": "2026-06-10",
                        "destination": "Test City",
                        "trip_cost": 2500,
                    },
                    "travelers": ["Synthetic Traveler"],
                }
            ],
            {"id": "policy_id", "customer_id": "customer_id", "plan": "plan"},
        )
        for claim_id, (outcome, payout) in SCENARIOS.items():
            claim = {
                "claim_id": claim_id,
                "customer_id": "CUS-E2E",
                "policy_id": "POL-E2E",
                "claim_type": "trip_delay",
                "summary": f"Synthetic {outcome} scenario",
                "incident_date": "2025-06-03" if outcome == "decline" else "2026-06-03",
                "submitted_on": "2026-06-05",
                "incident_location": "Test City",
                "story": "A crew problem delayed my flight 24 hours. I needed a hotel.",
                "amount_claimed": float(payout) or 100,
                "items": [
                    {
                        "description": "Hotel",
                        "category": "accommodation",
                        "amount": float(payout) or 100,
                    }
                ],
                "documents": []
                if outcome == "refer"
                else [
                    {
                        "name": "Carrier report",
                        "type": "carrier_report",
                        "content": "A crew problem delayed departure by 24 hours.",
                    },
                    {
                        "name": "Hotel receipt",
                        "type": "receipt",
                        "content": f"Hotel stay: ${payout}.",
                    },
                ],
            }
            connection.execute(
                "INSERT INTO claims (id, customer_id, policy_id, payload) "
                "VALUES (%s, 'CUS-E2E', 'POL-E2E', %s)",
                (claim_id, Jsonb(claim)),
            )
