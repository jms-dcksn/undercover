import json
import sys
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from agent import batch


def stored(state="completed", tasks=None):
    return {
        "id": "parent",
        "state": state,
        "tasks": tasks or [],
        "deadline": (datetime.now(UTC) + timedelta(seconds=6000)).isoformat(),
        "summary": "Saved queue summary" if state == "completed" else None,
        "error": "Coordinator failed" if state == "failed" else None,
    }


@pytest.mark.parametrize(
    ("limit", "claim_id"), [(None, None), (5, None), (None, "CLM-1001")]
)
def test_submit_one_parent_and_poll(limit, claim_id, monkeypatch, capsys):
    calls = []
    states = iter(
        [
            stored(
                "running", [{"claim_id": "CLM-1001", "state": "todo", "result": None}]
            ),
            stored(),
        ]
    )

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("/latest"):
            return httpx.Response(200, content="null")
        if request.method == "POST":
            return httpx.Response(202, json=stored("running"))
        return httpx.Response(200, json=next(states))

    monkeypatch.setattr(batch.time, "sleep", lambda _: None)
    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(handle)
    ) as client:
        assert batch.run(client, limit, claim_id) == 0
    submitted = [request for request in calls if request.method == "POST"]
    assert len(submitted) == 1
    body = json.loads(submitted[0].content)
    assert body["claim_limit"] == limit
    assert body["claim_id"] == claim_id
    assert "Saved queue summary" in capsys.readouterr().out


def test_attach_and_failed_exit(capsys):
    calls = []

    def handle(request):
        calls.append(request.method)
        return httpx.Response(
            200,
            json=stored(
                "running" if request.url.path.endswith("/latest") else "failed"
            ),
        )

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(handle)
    ) as client:
        assert batch.run(client) == 1
    assert calls == ["GET", "GET"]
    assert "no new work started" in capsys.readouterr().out


def test_racing_start_attaches_to_existing_run():
    latest = iter([None, stored("running")])

    def handle(request):
        if request.method == "POST":
            return httpx.Response(409, json={"detail": "active"})
        data = next(latest) if request.url.path.endswith("/latest") else stored()
        return httpx.Response(200, content=json.dumps(data))

    with httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(handle)
    ) as client:
        assert batch.run(client) == 0


def test_timeout_and_failed_task():
    expired = stored("running")
    expired["deadline"] = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    with (
        httpx.Client(
            base_url="http://test",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=expired)),
        ) as client,
        pytest.raises(TimeoutError, match="Parent deadline"),
    ):
        batch.wait_for_run(client, "/parent")
    failed = stored(
        tasks=[
            {
                "claim_id": "c",
                "state": "left_for_handler",
                "result": "technical failure 2/2",
            }
        ]
    )
    with httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=stored("running")
                if request.url.path.endswith("/latest")
                else failed,
            )
        ),
    ) as client:
        assert batch.run(client) == 1


@pytest.mark.parametrize(
    "arguments",
    [
        ["--limit", "0"],
        ["--limit", "-1"],
        ["--limit", "bad"],
        ["--limit", "5", "--claim", "x"],
        ["--unknown"],
    ],
)
def test_bad_flags(arguments, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["batch", *arguments])
    with pytest.raises(SystemExit) as error:
        batch.main()
    assert error.value.code == 2


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("offline"), KeyboardInterrupt(), None]
)
def test_main_exit_and_interruption(failure, monkeypatch, capsys):
    monkeypatch.setenv("BACKEND_URL", "http://queue-backend:9000")

    def run(client, limit, claim_id):
        assert str(client.base_url) == "http://queue-backend:9000"
        if failure:
            raise failure
        return 0

    monkeypatch.setattr(sys, "argv", ["batch", "--limit", "5"])
    monkeypatch.setattr(batch, "run", run)
    with pytest.raises(SystemExit) as error:
        batch.main()
    if isinstance(failure, KeyboardInterrupt):
        assert error.value.code == 130
        assert "Backend work may continue" in capsys.readouterr().out
    elif failure:
        assert "Queue watch stopped" in str(error.value)
    else:
        assert error.value.code == 0
