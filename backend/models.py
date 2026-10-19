"""Public API contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, model_validator

type QueueState = Literal["waiting", "in_progress", "waiting_for_sign_off", "decided"]
type Outcome = Literal["approve", "decline", "refer"]
type Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
type Text = Annotated[str, Field(min_length=1, max_length=4000)]


class ClaimSummary(BaseModel):
    claim_id: str
    customer_name: str
    plan: str
    claim_type: str
    summary: str
    amount_claimed: Money
    state: QueueState
    outcome: Outcome | None
    payout: Money | None
    payment_status: Literal["not_due", "pending", "blocked", "paid"]


class DecisionInput(BaseModel):
    run_id: UUID
    outcome: Outcome
    payout: Money
    explanation: Text
    policy_section: Annotated[int, Field(ge=1, le=12)]

    @model_validator(mode="after")
    def validate_payout(self) -> "DecisionInput":
        """Reject payouts attached to declines or referrals."""
        if self.outcome != "approve" and self.payout != 0:
            raise ValueError("Declines and referrals must have zero payout.")
        if not self.explanation.strip():
            raise ValueError("An explanation is required.")
        return self


class DecisionRecord(DecisionInput):
    claim_id: str
    created_at: datetime


class SignOffInput(BaseModel):
    handler_id: Text


class SignOffRecord(SignOffInput):
    claim_id: str
    handler_name: str
    created_at: datetime


class PaymentInput(BaseModel):
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


class PaymentRecord(PaymentInput):
    claim_id: str
    created_at: datetime


class ClaimDetail(BaseModel):
    summary: ClaimSummary
    claim: dict[str, JsonValue]
    policy: dict[str, JsonValue]
    plan: dict[str, JsonValue]
    plan_terms: dict[str, JsonValue]
    customer: dict[str, JsonValue]
    decision: DecisionRecord | None
    sign_off: SignOffRecord | None
    payment: PaymentRecord | None


class TextDocument(BaseModel):
    text: str


class Company(BaseModel):
    name: str
    currency: Literal["USD"]
    payout_approval_limit: Money
    policy_wording_version: str


class Handler(BaseModel):
    handler_id: str
    name: str
    role: str
    can_approve_over_limit: bool


class RunInput(BaseModel):
    thread_id: Text


class RunRecord(RunInput):
    id: UUID
    claim_id: str
    state: Literal["running", "completed", "failed"]
    created_at: datetime
    deadline: datetime
    finished_at: datetime | None


class ActivityRecord(BaseModel):
    id: int
    claim_id: str
    run_id: UUID | None
    kind: str
    message: str
    created_at: datetime
