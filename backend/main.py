"""The UnderCover backend."""

from fastapi import FastAPI

from backend import actions, queries
from backend.db import connect
from backend.models import (
    ClaimDetail,
    ClaimSummary,
    Company,
    DecisionInput,
    DecisionRecord,
    Handler,
    PaymentInput,
    PaymentRecord,
    SignOffInput,
    SignOffRecord,
    TextDocument,
)

app = FastAPI(title="UnderCover")


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims() -> list[ClaimSummary]:
    """Read the claims queue and each claim's current state."""
    return queries.queue()


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str) -> ClaimDetail:
    """Read the complete claim, supporting records and outcome."""
    return queries.detail(claim_id)


@app.get("/api/policy-wording", operation_id="get_policy_wording")
def get_policy_wording() -> TextDocument:
    """Read the full policy wording used for decisions."""
    with connect() as connection:
        return TextDocument.model_validate(queries.setting(connection, "wording"))


@app.get("/api/company", operation_id="get_company")
def get_company() -> Company:
    """Read company identity, currency and the payout approval limit."""
    with connect() as connection:
        return Company.model_validate(queries.setting(connection, "company"))


@app.get("/api/handlers", operation_id="get_handlers")
def get_handlers() -> list[Handler]:
    """Read the claims handlers and their sign-off eligibility."""
    return queries.handlers()


@app.get("/api/agent/instructions", operation_id="get_agent_instructions")
def get_agent_instructions() -> TextDocument:
    """Read the exact instructions supplied to the claims agent."""
    with connect() as connection:
        return TextDocument.model_validate(queries.setting(connection, "instructions"))


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, request: DecisionInput) -> DecisionRecord:
    """Record the agent's decision, explanation, payout and policy section."""
    return actions.decide(claim_id, request)


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(claim_id: str, request: SignOffInput) -> SignOffRecord:
    """Sign off an over-limit approval using an eligible handler record."""
    return actions.sign_off(claim_id, request)


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, request: PaymentInput) -> PaymentRecord:
    """Simulate payment for the exact approved amount after any required sign-off."""
    return actions.pay(claim_id, request)
