import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent import main
from agent.tests.test_agent import StubModel, reply
from backend import db, documents, manage
from backend.main import app

client = TestClient(app)


@pytest.mark.parametrize(
    ("document", "filename", "version", "count"),
    [
        ("manual", "claims_manual.md", "2026.2", 14),
        ("wording", "policy_wording.md", "2026.1", 12),
    ],
)
def test_exact_section_index(document, filename, version, count, database):
    original = (manage.DATA / filename).read_text()
    sections = documents.split_sections(document, original)
    assert len(sections) == count
    assert all(section.version == version for section in sections)
    assert (
        "".join(section.text for section in sections)
        == original[original.index("## 1.") :]
    )
    headings = client.get(f"/api/documents/{document}/sections").json()
    assert len(headings) == count
    assert "text" not in headings[0]
    assert client.get("/api/documents/unknown/sections").status_code == 404
    assert client.post("/api/documents/search", json={"query": ""}).json() == []
    assert (
        client.post("/api/documents/search", json={"query": "nonexistent-term"}).json()
        == []
    )
    matches = client.post(
        "/api/documents/search", json={"query": "wild animals"}
    ).json()
    assert matches[0]["document"] == "manual"
    assert matches[0]["section"] == 7
    assert len(matches[0]["snippet"]) <= 300
    with pytest.raises(ValueError, match="version"):
        documents.split_sections("manual", "## 1. No version")


def test_reads_scoped_to_active_attempt_and_exact_text(claim_run):
    path = f"/api/claims/TEST-CLAIM/runs/{claim_run}/sections"
    response = client.post(path, json={"document": "manual", "section": 5})
    assert response.status_code == 200
    read = response.json()
    assert read["run_id"] == claim_run
    assert read["version"] == "2026.2"
    assert "| Benefit | Required documents |" in read["text"]
    assert client.get("/api/claims/TEST-CLAIM/sections").json() == [read]
    assert client.get("/api/claims/CLM-1001/sections").json() == []
    assert client.get("/api/claims/missing/sections").status_code == 404
    assert (
        client.post(path, json={"document": "manual", "section": 99}).status_code == 404
    )
    assert (
        client.post(path, json={"document": "unknown", "section": 1}).status_code == 404
    )
    assert (
        client.post(
            path.replace("TEST-CLAIM", "CLM-1001"),
            json={"document": "manual", "section": 5},
        ).status_code
        == 409
    )
    with db.connect() as connection:
        connection.execute("UPDATE runs SET deadline = now() - interval '1 second'")
    assert (
        client.post(path, json={"document": "manual", "section": 5}).status_code == 409
    )


@pytest.mark.parametrize(
    "scenario",
    [
        (
            9,
            "Two prior claims in 12 months; this is the third.",
            "refer",
            "0",
            "Third claim in 12 months needs Special Investigations. Potential "
            "payable amount is $215.",
        ),
        (
            7,
            "A wild monkey damaged a bag; guide statement and repair estimate "
            "attached.",
            "approve",
            "215",
            "Wild animal accidental damage is covered. Eligible $315 less "
            "$100 deductible is $215.",
        ),
        (
            10,
            "Two travelers delayed 30 hours, no meal receipts.",
            "approve",
            "140",
            "Covered delay meals allowance is $35 per traveler per started "
            "day. Two travelers times two days pays $140.",
        ),
        (
            5,
            "Police report is missing.",
            "refer",
            "0",
            "A required police report is missing. Refer for that document.",
        ),
        (
            5,
            "The customer says theft was never reported to police.",
            "decline",
            "0",
            "The theft was never reported to police. The condition in policy "
            "section 5 is unmet.",
        ),
        (
            6,
            "Eligible $90 baggage loss with $100 deductible.",
            "decline",
            "0",
            "The deductible exceeds eligible expenses. No payout remains "
            "under policy section 10.",
        ),
    ],
)
def test_manual_scenarios_via_http_tools(scenario, claim_run, http_backend):
    section, fact, outcome, amount, reason = scenario
    with db.connect() as connection:
        connection.execute(
            "UPDATE claims SET payload = jsonb_set(payload, '{story}', %s) "
            "WHERE id = 'TEST-CLAIM'",
            ('"' + fact + '"',),
        )
    messages = [
        reply("read_claim", {}, "claim"),
        reply("list_sections", {"document": "manual"}, "headings"),
        reply("search_sections", {"query": "claim"}, "search"),
        reply("read_section", {"document": "manual", "section": section}, "manual"),
        reply("read_section", {"document": "wording", "section": 5}, "wording"),
        reply(
            "record_decision",
            {
                "outcome": outcome,
                "payout": amount,
                "explanation": reason,
                "policy_section": 5,
            },
            "save",
        ),
        AIMessage(content="Saved"),
    ]
    asyncio.run(
        main.arun("TEST-CLAIM", "test-thread", StubModel(responses=[*messages]))
    )
    detail = client.get("/api/claims/TEST-CLAIM").json()
    assert detail["decision"]["manual_version"] == "2026.2"
    assert detail["decision"]["outcome"] == outcome
    assert client.get("/api/claims/TEST-CLAIM/sections").json()[0]["section"] == section


def test_both_instruction_sets_match_backend_files(database):
    instructions = client.get("/api/agent/instructions").json()
    assert instructions["claim"] == Path("backend/instructions.md").read_text()
    assert instructions["queue"] == Path("backend/queue_instructions.md").read_text()
