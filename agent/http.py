"""Backend transport, tool activity and ambiguous-write recovery."""

import json
from typing import Any

import httpx

import telemetry
from agent.config import backend_url


async def trace_request(request: httpx.Request) -> None:
    telemetry.inject_headers(request.headers)


def backend() -> httpx.AsyncClient:
    """Create the shared asynchronous backend client."""
    return httpx.AsyncClient(
        base_url=backend_url(), timeout=30, event_hooks={"request": [trace_request]}
    )


class ClaimHTTP:
    """Record actual tool events around scoped HTTP requests."""

    def __init__(self, client: httpx.AsyncClient, claim_path: str, run_id: str):
        self.client = client
        self.claim_path = claim_path
        self.event_path = f"{claim_path}/runs/{run_id}/activity"

    async def event(self, kind: str, message: str) -> None:
        response = await self.client.post(
            self.event_path, json={"kind": kind, "message": message}
        )
        response.raise_for_status()

    async def call(
        self, name: str, method: str, path: str, body: dict[str, Any] | None
    ) -> str:
        await self.event("tool_started", name)
        try:
            response = await self.client.request(method, path, json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            await self.event(
                "tool_error",
                f"{name}: request rejected ({error.response.status_code}).",
            )
            return json.dumps(
                {"error": error.response.json(), "status": error.response.status_code}
            )
        except httpx.RequestError:
            await self.event("tool_error", f"{name}: backend connection failed.")
            saved = await self.recover(method, path)
            if saved is None:
                raise
            response = httpx.Response(200, json=saved)
        await self.event("tool_finished", name)
        return response.text

    async def recover(self, method: str, path: str) -> dict | None:
        """Read saved business actions after an ambiguous write response."""
        key = "decision" if path.endswith("/decision") else "payment"
        if method != "POST" or not path.endswith(("/decision", "/payment")):
            return None
        response = await self.client.get(self.claim_path)
        response.raise_for_status()
        return response.json()[key]
