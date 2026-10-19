import json
import sys
from uuid import UUID

import httpx
import pytest

from agent import batch


@pytest.mark.parametrize("failed_claim", [None, "CLM-1002"])
def test_processes_25_claims_sequentially_and_skips_other_states(
    failed_claim, monkeypatch, capsys
):
    claims = [
        {"claim_id": f"CLM-{number}", "state": "waiting"}
        for number in range(1001, 1026)
    ]
    claims.extend(
        {"claim_id": state, "state": state}
        for state in ("decided", "waiting_for_sign_off", "in_progress")
    )
    active = None
    polled = False
    started = []
    threads = []

    def handle(request):
        nonlocal active, polled
        if request.url.path == "/api/claims":
            return httpx.Response(200, json=claims)
        claim_id = request.url.path.split("/")[3]
        if request.method == "POST":
            assert active is None
            active, polled = claim_id, False
            started.append(claim_id)
            threads.append(UUID(json.loads(request.content)["thread_id"]))
            return httpx.Response(202, json={"state": "running"})
        assert active == claim_id
        if not polled:
            polled = True
            return httpx.Response(200, json={"state": "running"})
        active = None
        state = "failed" if claim_id == failed_claim else "completed"
        return httpx.Response(200, json={"state": state})

    monkeypatch.setattr(batch.time, "sleep", lambda _: None)
    with httpx.Client(
        transport=httpx.MockTransport(handle), base_url="http://test"
    ) as client:
        assert batch.run(client) == int(failed_claim is not None)
    assert started == [claim["claim_id"] for claim in claims[:25]]
    assert len(set(threads)) == 25
    assert active is None
    output = capsys.readouterr().out
    assert "Processing 25 waiting claims; 3 skipped." in output
    expected = "24 completed, 1 failed" if failed_claim else "25 completed, 0 failed"
    assert expected in output


def test_empty_queue_does_not_start_runs(capsys):
    def handle(request):
        assert request.url.path == "/api/claims"
        return httpx.Response(200, json=[])

    with httpx.Client(
        transport=httpx.MockTransport(handle), base_url="http://test"
    ) as client:
        assert batch.run(client) == 0
    assert "Finished: 0 completed, 0 failed." in capsys.readouterr().out


def test_polling_timeout_stops_the_batch(monkeypatch):
    clock = iter([0, 0, batch.WAIT_SECONDS + 1])
    monkeypatch.setattr(batch.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(batch.time, "sleep", lambda _: None)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"state": "running"})
    )
    with (
        httpx.Client(transport=transport, base_url="http://test") as client,
        pytest.raises(TimeoutError, match="inspect the claim"),
    ):
        batch.wait_for_run(client, "/api/claims/CLM-1001/run")


@pytest.mark.parametrize("state", ["completed", "failed"])
def test_command_configuration_and_exit_status(state, monkeypatch, capsys):
    def handle(request):
        assert request.url.host == "configured-backend"
        if request.url.path == "/api/claims":
            return httpx.Response(
                200, json=[{"claim_id": "CLM-1001", "state": "waiting"}]
            )
        return httpx.Response(200, json={"state": state})

    client_factory = httpx.Client
    monkeypatch.setattr(
        batch.httpx,
        "Client",
        lambda **kwargs: client_factory(
            transport=httpx.MockTransport(handle), **kwargs
        ),
    )
    monkeypatch.setenv("BACKEND_URL", "http://configured-backend")
    monkeypatch.setattr(sys, "argv", ["batch"])
    with pytest.raises(SystemExit) as error:
        batch.main()
    assert error.value.code == (1 if state == "failed" else 0)
    assert f"CLM-1001: {state}" in capsys.readouterr().out


@pytest.mark.parametrize("status", [409, 503])
def test_http_error_stops_with_a_useful_message(status, monkeypatch):
    def fail(client):
        response = httpx.Response(status, request=httpx.Request("POST", "http://test"))
        response.raise_for_status()

    monkeypatch.setattr(batch, "run", fail)
    monkeypatch.setattr(sys, "argv", ["batch"])
    with pytest.raises(SystemExit, match=f"Batch stopped:.*{status}"):
        batch.main()


def test_interrupt_explains_that_the_backend_run_continues(monkeypatch, capsys):
    def interrupt(client):
        raise KeyboardInterrupt

    monkeypatch.setattr(batch, "run", interrupt)
    monkeypatch.setattr(sys, "argv", ["batch"])
    with pytest.raises(SystemExit) as error:
        batch.main()
    assert error.value.code == 130
    assert "current agent run may still finish" in capsys.readouterr().out
