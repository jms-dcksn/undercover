from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import db, manage
from backend.main import app

client = TestClient(app)
PATH = "/api/claims/TEST-CLAIM"


def decision(run_id, payout="1000.01", outcome="approve"):
    return {
        "run_id": run_id,
        "outcome": outcome,
        "payout": payout,
        "explanation": "The carrier delay meets the policy waiting period. "
        "Eligible documented expenses are payable under section 3.",
        "policy_section": 3,
    }


@pytest.mark.parametrize("amount", ["999.99", "1000.00", "1000.01"])
def test_payment_boundary(amount, claim_run):
    response = client.post(f"{PATH}/decision", json=decision(claim_run, amount))
    assert response.status_code == 200
    assert response.json()["payout"] == amount
    payment = client.post(f"{PATH}/payment", json={"amount": amount})
    detail = client.get(PATH).json()
    if amount == "1000.01":
        assert payment.status_code == 409
        assert detail["summary"]["state"] == "waiting_for_sign_off"
        assert detail["payment"] is None
        assert (
            client.post(f"{PATH}/payment", json={"amount": "1000.00"}).status_code
            == 409
        )
    else:
        assert payment.status_code == 200
        assert detail["summary"]["state"] == "decided"
        assert detail["summary"]["payment_status"] == "paid"


def test_sign_off_and_idempotent_payment(claim_run):
    client.post(f"{PATH}/decision", json=decision(claim_run))
    assert (
        client.post(f"{PATH}/sign-off", json={"handler_id": "missing"}).status_code
        == 404
    )
    with db.connect() as connection:
        connection.execute(
            "UPDATE handlers SET can_sign_off = false WHERE id = 'HND-03'"
        )
    assert (
        client.post(f"{PATH}/sign-off", json={"handler_id": "HND-03"}).status_code
        == 403
    )
    first = client.post(f"{PATH}/sign-off", json={"handler_id": "HND-01"})
    assert first.status_code == 200
    assert (
        client.post(f"{PATH}/sign-off", json={"handler_id": "HND-01"}).json()
        == first.json()
    )
    assert (
        client.post(f"{PATH}/sign-off", json={"handler_id": "HND-02"}).status_code
        == 409
    )
    payment = client.post(f"{PATH}/payment", json={"amount": "1000.01"})
    assert payment.status_code == 200
    assert (
        client.post(f"{PATH}/payment", json={"amount": "1000.01"}).json()
        == payment.json()
    )
    result = client.get(PATH).json()
    assert result["decision"]["outcome"] == "approve"
    assert result["sign_off"]["handler_name"] == "Dana Whitfield"
    assert result["summary"]["state"] == "decided"
    assert result["summary"]["payment_status"] == "paid"
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM payments").fetchone() == {
            "n": 1
        }


@pytest.mark.parametrize("outcome", ["decline", "refer", "approve"])
def test_zero_decisions_are_not_payable(outcome, claim_run):
    response = client.post(
        f"{PATH}/decision", json=decision(claim_run, "0.00", outcome)
    )
    assert response.status_code == 200
    assert client.post(f"{PATH}/payment", json={"amount": "10.00"}).status_code == 409
    assert (
        client.post(f"{PATH}/sign-off", json={"handler_id": "HND-01"}).status_code
        == 409
    )
    assert client.get(PATH).json()["summary"]["payment_status"] == "not_due"


@pytest.mark.parametrize("amount", ["-1", "0", "invalid", "NaN", "Infinity", "1.001"])
def test_invalid_payment_amounts(amount, claim_run):
    assert client.post(f"{PATH}/payment", json={"amount": amount}).status_code == 422


def test_unapproved_and_mismatched_payments(claim_run):
    assert client.post(f"{PATH}/payment", json={"amount": "10"}).status_code == 409
    assert (
        client.post(f"{PATH}/sign-off", json={"handler_id": "HND-01"}).status_code
        == 404
    )
    assert (
        client.post("/api/claims/missing/payment", json={"amount": "10"}).status_code
        == 404
    )
    client.post(f"{PATH}/decision", json=decision(claim_run, "500.00"))
    assert client.get(PATH).json()["summary"]["payment_status"] == "pending"
    assert client.post(f"{PATH}/payment", json={"amount": "100"}).status_code == 409


def test_decision_validation_and_run_ownership(claim_run):
    assert (
        client.post(f"{PATH}/decision", json=decision(str(uuid4()))).status_code == 409
    )
    assert (
        client.post(
            f"{PATH}/decision", json=decision(claim_run, "1", "decline")
        ).status_code
        == 422
    )
    body = decision(claim_run)
    body["explanation"] = " "
    assert client.post(f"{PATH}/decision", json=body).status_code == 422
    body = decision(claim_run)
    body["policy_section"] = 13
    assert client.post(f"{PATH}/decision", json=body).status_code == 422
    with db.connect() as connection:
        connection.execute(
            'UPDATE settings SET payload = \'{"text": "missing"}\' '
            "WHERE key = 'wording'"
        )
    assert client.post(f"{PATH}/decision", json=decision(claim_run)).status_code == 422


def test_expired_run_cannot_decide(claim_run):
    with db.connect() as connection:
        connection.execute("UPDATE runs SET deadline = now() - interval '1 second'")
    assert client.post(f"{PATH}/decision", json=decision(claim_run)).status_code == 409


def test_concurrent_decisions_and_payments(claim_run):
    def decide(_):
        return client.post(
            f"{PATH}/decision", json=decision(claim_run, "999.99")
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(decide, range(2))) == [200, 409]

    def pay(_):
        return client.post(f"{PATH}/payment", json={"amount": "999.99"}).json()

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = workers.map(pay, range(2))
    assert first == second
    manage.seed()
    detail = client.get(PATH).json()
    assert detail["decision"]["payout"] == "999.99"
    assert detail["payment"]["amount"] == "999.99"
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM payments").fetchone() == {
            "n": 1
        }
