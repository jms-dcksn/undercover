"""The UnderCover backend."""

import asyncio
from contextlib import asynccontextmanager, suppress
from uuid import UUID

import psycopg
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

import telemetry
from backend import (
    actions,
    coordinator,
    documents,
    queries,
    queue_runs,
    recovery,
    runs,
    worker,
)
from backend.db import DatabaseNotConfigured, connect
from backend.models import (
    ActivityInput,
    ActivityRecord,
    ClaimDetail,
    ClaimSummary,
    Company,
    DecisionInput,
    DecisionRecord,
    DelegateInput,
    Handler,
    Instructions,
    PaymentInput,
    PaymentRecord,
    QueueRunInput,
    QueueRunRecord,
    Reconciliation,
    RunInput,
    RunRecord,
    SearchInput,
    SectionInput,
    SectionMatch,
    SectionRead,
    SectionReference,
    SignOffInput,
    SignOffRecord,
    TasksInput,
    TextDocument,
)
from backend.records import setting


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Recover interrupted ownership and monitor deadlines in this one process."""
    await asyncio.to_thread(recovery.recover_all, True)
    watcher = asyncio.create_task(recovery.watchdog())
    try:
        yield
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        await asyncio.to_thread(telemetry.shutdown)


app = FastAPI(title="UnderCover", lifespan=lifespan)


@app.exception_handler(DatabaseNotConfigured)
async def missing_database(
    request: Request, error: DatabaseNotConfigured
) -> JSONResponse:
    """Return a useful setup error without exposing connection credentials."""
    return JSONResponse(status_code=503, content={"detail": str(error)})


@app.exception_handler(psycopg.Error)
async def unavailable_database(request: Request, error: psycopg.Error) -> JSONResponse:
    """Keep database failures out of public API responses."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Claims database unavailable. Check the backend connection."
        },
    )


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
        return TextDocument.model_validate(setting(connection, "wording"))


@app.get("/api/company", operation_id="get_company")
def get_company() -> Company:
    """Read company identity, currency and the payout approval limit."""
    with connect() as connection:
        return Company.model_validate(setting(connection, "company"))


@app.get("/api/handlers", operation_id="get_handlers")
def get_handlers() -> list[Handler]:
    """Read the claims handlers and their sign-off eligibility."""
    return queries.handlers()


@app.get("/api/agent/instructions", operation_id="get_agent_instructions")
def get_agent_instructions() -> Instructions:
    """Read the exact instructions supplied to the claims agent."""
    with connect() as connection:
        claim = setting(connection, "instructions")["text"]
        return Instructions(
            text=claim,
            claim=claim,
            queue=setting(connection, "queue_instructions")["text"],
        )


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


@app.post("/api/claims/{claim_id}/run", operation_id="start_claim", status_code=202)
def start_claim(
    claim_id: str, request: RunInput, background_tasks: BackgroundTasks
) -> RunRecord:
    """Reserve a waiting claim and start its agent in the background."""
    run = runs.start(claim_id, request.thread_id)
    background_tasks.add_task(coordinator.execute_named, run)
    return run


@app.get("/api/claims/{claim_id}/run", operation_id="get_claim_run")
def get_claim_run(claim_id: str) -> RunRecord:
    """Read the most recent agent run for a claim."""
    return runs.current(claim_id)


@app.get("/api/claims/{claim_id}/activity", operation_id="get_claim_activity")
def get_claim_activity(claim_id: str) -> list[ActivityRecord]:
    """Read the claim's ordered, timestamped execution activity."""
    return runs.events(claim_id)


@app.post(
    "/api/claims/{claim_id}/runs/{run_id}/activity", operation_id="record_tool_activity"
)
def record_tool_activity(
    claim_id: str, run_id: UUID, request: ActivityInput
) -> ActivityRecord:
    """Record one observable tool event for the active claim run."""
    return runs.record_event(claim_id, run_id, request)


@app.post("/api/agent/runs", operation_id="start_queue_run", status_code=202)
def start_queue_run(
    request: QueueRunInput, background_tasks: BackgroundTasks
) -> QueueRunRecord:
    """Start a stored queue run over a snapshot of eligible claims."""
    parent = queue_runs.start(request)
    background_tasks.add_task(coordinator.execute, parent)
    return parent


@app.get("/api/agent/runs/latest", operation_id="latest_queue_run")
def latest_queue_run() -> QueueRunRecord | None:
    """Read the current or most recent stored queue run."""
    return queue_runs.latest()


@app.get("/api/agent/runs/{run_id}", operation_id="get_queue_run")
def get_queue_run(run_id: UUID) -> QueueRunRecord:
    """Read a stored queue run and its ordered tasks."""
    return queue_runs.get(run_id)


@app.put("/api/agent/runs/{run_id}/tasks", operation_id="write_queue_tasks")
def write_queue_tasks(run_id: UUID, request: TasksInput) -> QueueRunRecord:
    """Validate and store the queue agent's ordered to-do list."""
    return queue_runs.write_tasks(run_id, request)


@app.post(
    "/api/agent/runs/{run_id}/delegate", operation_id="delegate_claim", status_code=202
)
def delegate_claim(
    run_id: UUID,
    request: DelegateInput,
    background_tasks: BackgroundTasks,
    http_request: Request,
) -> RunRecord:
    """Reserve a cap slot and start a fresh bounded claim attempt."""
    attempt = queue_runs.delegate(run_id, request.claim_id)
    background_tasks.add_task(
        worker.execute, attempt, http_request.headers.get("traceparent")
    )
    return attempt


@app.get("/api/agent/runs/{run_id}/reconciliation", operation_id="reconcile_queue_run")
def reconcile_queue_run(run_id: UUID) -> Reconciliation:
    """Check for missing work, active attempts and required retries."""
    return queue_runs.reconcile(run_id)


@app.post("/api/agent/runs/{run_id}/complete", operation_id="complete_queue_run")
def complete_queue_run(run_id: UUID) -> QueueRunRecord:
    """Reconcile authoritative outcomes and save the final run summary."""
    return queue_runs.complete(run_id)


@app.get("/api/documents/{document}/sections", operation_id="list_sections")
def list_sections(document: str) -> list[SectionReference]:
    """List section headings and the current version of a business document."""
    return documents.headings(document)


@app.post("/api/documents/search", operation_id="search_sections")
def search_sections(request: SearchInput) -> list[SectionMatch]:
    """Search policy wording and manual sections with bounded snippets."""
    return documents.search(request.query)


@app.post("/api/claims/{claim_id}/runs/{run_id}/sections", operation_id="read_section")
def read_section(claim_id: str, run_id: UUID, request: SectionInput) -> SectionRead:
    """Return and persist the exact text read by the scoped active attempt."""
    return documents.read(claim_id, run_id, request)


@app.get("/api/claims/{claim_id}/sections", operation_id="get_section_reads")
def get_section_reads(claim_id: str) -> list[SectionRead]:
    """Read the versioned sections retrieved for this claim's attempts."""
    return documents.reads(claim_id)


@app.get("/api/agent/runs/{run_id}/claims", operation_id="get_run_claim_summaries")
def get_run_claim_summaries(run_id: UUID) -> list[ClaimSummary]:
    """Read only the summaries in this run's immutable snapshot."""
    parent = queue_runs.get(run_id)
    return [claim for claim in queries.queue() if claim.claim_id in parent.snapshot]


@app.post(
    "/api/claims/{claim_id}/runs/{run_id}/payment", operation_id="pay_from_attempt"
)
def pay_from_attempt(
    claim_id: str, run_id: UUID, request: PaymentInput
) -> PaymentRecord:
    """Simulate payment only from an active unexpired claim attempt."""
    return actions.pay_scoped(claim_id, run_id, request)
