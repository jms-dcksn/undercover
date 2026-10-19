import inspect
import json

import psycopg
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend import db, manage
from backend.main import app

client = TestClient(app)


def test_queue_and_full_claim(database):
    response = client.get("/api/claims")
    assert response.status_code == 200
    claims = response.json()
    assert len(claims) == 25
    assert {claim["state"] for claim in claims} == {"waiting"}
    detail = client.get("/api/claims/CLM-1001").json()
    original = json.loads((manage.DATA / "claims.json").read_text())[0]
    assert detail["claim"] == original
    assert detail["policy"]["policy_id"] == "POL-2001"
    assert detail["plan"]["plan"] == "premium"
    assert detail["customer"]["previous_claims"][0]["claim_id"] == "CLM-0412"
    assert detail["summary"]["amount_claimed"] == "420.0"
    assert detail["decision"] is None
    assert detail["payment"] is None


def test_documents_and_reference_data(database):
    wording = client.get("/api/policy-wording")
    assert wording.status_code == 200
    assert wording.json()["text"] == (manage.DATA / "policy_wording.md").read_text()
    instructions = client.get("/api/agent/instructions")
    assert (
        instructions.json()["text"]
        == manage.ROOT.joinpath("backend/instructions.md").read_text()
    )
    company = client.get("/api/company").json()
    assert company["payout_approval_limit"] == "1000.0"
    assert "repeat_claim_review" not in company
    assert len(client.get("/api/handlers").json()) == 3
    assert (
        client.post("/api/agent/instructions", json={"text": "changed"}).status_code
        == 405
    )


def test_missing_records_and_seed(database):
    assert client.get("/api/claims/missing").status_code == 404
    with db.connect() as connection:
        connection.execute("DELETE FROM settings WHERE key = 'wording'")
    assert client.get("/api/policy-wording").status_code == 503
    assert client.get("/api/files/data/evals/decisions.json").status_code == 404


def test_operation_contracts():
    schema = app.openapi()
    operations = [
        operation for path in schema["paths"].values() for operation in path.values()
    ]
    identifiers = [operation["operationId"] for operation in operations]
    assert len(set(identifiers)) == len(identifiers)
    for operation in operations:
        assert all(
            parameter["required"] for parameter in operation.get("parameters", [])
        )
    for route in app.routes:
        if isinstance(route, APIRoute):
            assert len((inspect.getdoc(route.endpoint) or "").splitlines()) == 1
    assert not any("manual" in path or "eval" in path for path in schema["paths"])


def test_database_configuration_errors(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = client.get("/api/claims")
    assert response.status_code == 503
    assert "Set DATABASE_URL" in response.json()["detail"]
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/undercover")

    def unavailable(*args, **kwargs):
        raise psycopg.OperationalError("private connection details")

    monkeypatch.setattr(psycopg.Connection, "connect", unavailable)
    response = client.get("/api/claims")
    assert response.status_code == 503
    assert "private connection details" not in response.text
