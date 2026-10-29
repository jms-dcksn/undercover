"""Public API contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, model_validator

type QueueState = Literal[
    "waiting", "in_progress", "waiting_for_sign_off", "decided", "needs_handler"
]
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
    manual_version: str | None
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
    run: "RunRecord | None"


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
    parent_id: UUID | None = None
    error: str | None = None
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


class ActivityInput(BaseModel):
    kind: Literal["tool_started", "tool_finished", "tool_error"]
    message: Text


type TaskState = Literal["todo", "in_progress", "done", "left_for_handler"]


class QueueRunInput(BaseModel):
    thread_id: Text
    claim_limit: Annotated[int, Field(gt=0, strict=True)] | None
    claim_id: Text | None

    @model_validator(mode="after")
    def validate_scope(self) -> "QueueRunInput":
        """Keep named and capped scopes mutually exclusive."""
        if self.claim_id is not None and self.claim_limit is not None:
            raise ValueError("Choose a claim or a limit, not both.")
        return self


class TaskInput(BaseModel):
    claim_id: Text
    description: Text
    state: TaskState


class TaskRecord(TaskInput):
    parent_id: UUID
    position: int
    admitted: bool
    result: str | None


class TasksInput(BaseModel):
    tasks: Annotated[list[TaskInput], Field(max_length=1000)]


class DelegateInput(BaseModel):
    claim_id: Text


class QueueRunRecord(QueueRunInput):
    id: UUID
    mode: Literal["queue", "named"]
    snapshot: list[str]
    state: Literal["running", "completed", "failed"]
    summary: str | None
    error: str | None
    created_at: datetime
    deadline: datetime
    finished_at: datetime | None
    tasks: list[TaskRecord]


class Reconciliation(BaseModel):
    ready: bool
    missing: list[str]
    retry: list[str]
    active: list[str]
    slots_remaining: int
    outside_cap: int


class Instructions(TextDocument):
    queue: str
    claim: str


class SectionReference(BaseModel):
    document: Literal["wording", "manual"]
    version: str
    section: int
    heading: str


class DocumentSection(SectionReference):
    text: str


class SectionRead(DocumentSection):
    id: int
    claim_id: str
    run_id: UUID
    created_at: datetime


class SectionInput(BaseModel):
    document: Literal["wording", "manual"]
    section: Annotated[int, Field(gt=0)]


class SearchInput(BaseModel):
    query: Annotated[str, Field(max_length=200)]


class SectionMatch(SectionReference):
    snippet: str
