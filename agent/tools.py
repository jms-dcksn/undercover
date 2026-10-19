"""Claim-scoped tools that access business data only through HTTP."""

import json
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool


def claim_tools(
    client: httpx.AsyncClient, claim_id: str, run_id: str
) -> list[BaseTool]:
    """Bind tools to one claim and record their actual execution."""
    claim_path = f"/api/claims/{claim_id}"
    event_path = f"{claim_path}/runs/{run_id}/activity"

    async def event(kind: str, message: str) -> None:
        response = await client.post(
            event_path, json={"kind": kind, "message": message}
        )
        response.raise_for_status()

    async def call(
        name: str, method: str, path: str, body: dict[str, Any] | None
    ) -> str:
        await event("tool_started", name)
        try:
            response = await client.request(method, path, json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            await event(
                "tool_error",
                f"{name}: request rejected ({error.response.status_code}).",
            )
            return json.dumps(
                {"error": error.response.json(), "status": error.response.status_code}
            )
        except httpx.RequestError:
            await event("tool_error", f"{name}: backend connection failed.")
            raise
        await event("tool_finished", name)
        return response.text

    @tool
    async def read_claim() -> str:
        """Read the claim, all documents, policy, plan and customer history."""
        return await call("Read claim and supporting records", "GET", claim_path, None)

    @tool
    async def read_policy_wording() -> str:
        """Read the full policy wording that governs the claim."""
        return await call("Read policy wording", "GET", "/api/policy-wording", None)

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
            f"{claim_path}/payment",
            {"amount": amount},
        )

    return [
        read_claim,
        read_policy_wording,
        read_company,
        record_decision,
        request_payment,
    ]
