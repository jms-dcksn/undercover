"""Claim-scoped tools that access business data only through HTTP."""

import httpx
from langchain_core.tools import BaseTool, tool

from agent.http import ClaimHTTP


def claim_tools(
    client: httpx.AsyncClient, claim_id: str, run_id: str
) -> list[BaseTool]:
    """Bind tools to one claim and record their actual execution."""
    claim_path = f"/api/claims/{claim_id}"
    call = ClaimHTTP(client, claim_path, run_id).call

    @tool
    async def read_claim() -> str:
        """Read the claim, all documents, policy, plan and customer history."""
        return await call("Read claim and supporting records", "GET", claim_path, None)

    @tool
    async def list_sections(document: str) -> str:
        """List numbered section headings for wording or manual."""
        return await call(
            "List document sections", "GET", f"/api/documents/{document}/sections", None
        )

    @tool
    async def search_sections(query: str) -> str:
        """Search both documents for section references and short snippets."""
        return await call(
            "Search document sections",
            "POST",
            "/api/documents/search",
            {"query": query},
        )

    @tool
    async def read_section(document: str, section: int) -> str:
        """Read a complete numbered section of wording or manual for this attempt."""
        return await call(
            "Read document section",
            "POST",
            f"{claim_path}/runs/{run_id}/sections",
            {"document": document, "section": section},
        )

    @tool
    async def read_company() -> str:
        """Read the currency and payout approval limit."""
        return await call("Read payout approval limit", "GET", "/api/company", None)

    @tool
    async def record_decision(
        outcome: str, payout: str, explanation: str, policy_section: int
    ) -> str:
        """Save approve, decline or refer with USD payout, explanation and section."""
        return await call(
            "Record decision",
            "POST",
            f"{claim_path}/decision",
            {
                "run_id": run_id,
                "outcome": outcome,
                "payout": payout,
                "explanation": explanation,
                "policy_section": policy_section,
            },
        )

    @tool
    async def request_payment(amount: str) -> str:
        """Request a simulated payment for the exact approved USD payout."""
        return await call(
            "Request simulated payment",
            "POST",
            f"{claim_path}/runs/{run_id}/payment",
            {"amount": amount},
        )

    return [
        read_claim,
        list_sections,
        search_sections,
        read_section,
        read_company,
        record_decision,
        request_payment,
    ]
