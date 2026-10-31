"""Small versioned section index for the two approved business documents."""

import re
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from backend.db import Connection, connect
from backend.models import (
    DocumentSection,
    SectionInput,
    SectionMatch,
    SectionRead,
    SectionReference,
)
from backend.records import active_run, required


def split_sections(document: str, text: str) -> list[DocumentSection]:
    """Preserve numbered headings, body text and whitespace exactly."""
    version = re.search(r"^Version (\d+\.\d+)", text, re.MULTILINE)
    if version is None:
        raise ValueError("Document version is missing.")
    headings = list(re.finditer(r"^## (\d+)\. (.+)$", text, re.MULTILINE))
    return [
        DocumentSection.model_validate(
            {
                "document": document,
                "version": version[1],
                "section": int(match[1]),
                "heading": match[0],
                "text": text[
                    match.start() : headings[index + 1].start()
                    if index + 1 < len(headings)
                    else len(text)
                ],
            }
        )
        for index, match in enumerate(headings)
    ]


def load(connection: Connection, data: Path) -> None:
    """Read only the explicit wording/manual allowlist and backend instructions."""
    for document, filename in (
        ("wording", "policy_wording.md"),
        ("manual", "claims_manual.md"),
    ):
        sections = split_sections(document, (data / filename).read_text())
        for section in sections:
            connection.execute(
                "INSERT INTO document_sections "
                "(document, version, section, heading, text) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (
                    section.document,
                    section.version,
                    section.section,
                    section.heading,
                    section.text,
                ),
            )
        connection.execute(
            "INSERT INTO settings VALUES (%s, %s) ON CONFLICT (key) "
            "DO UPDATE SET payload = EXCLUDED.payload",
            (f"{document}_version", Jsonb({"version": sections[0].version})),
        )
    for key, filename in (
        ("instructions", "instructions.md"),
        ("queue_instructions", "queue_instructions.md"),
    ):
        connection.execute(
            "INSERT INTO settings VALUES (%s, %s) ON CONFLICT (key) "
            "DO UPDATE SET payload = EXCLUDED.payload",
            (key, Jsonb({"text": Path(__file__).with_name(filename).read_text()})),
        )


def headings(document: str) -> list[SectionReference]:
    """List the current version's headings without document bodies."""
    with connect() as connection:
        rows = connection.execute(
            "SELECT d.* FROM document_sections d JOIN settings s "
            "ON s.key = d.document || '_version' "
            "AND s.payload->>'version' = d.version "
            "WHERE document = %s ORDER BY section",
            (document,),
        ).fetchall()
        if not rows:
            raise HTTPException(404, "Document not found.")
        return [SectionReference.model_validate(row) for row in rows]


def search(query: str) -> list[SectionMatch]:
    """Search current sections with bounded snippets and an explicit empty list."""
    terms = query.lower().split()
    if not terms:
        return []
    with connect() as connection:
        rows = connection.execute(
            "SELECT d.* FROM document_sections d JOIN settings s "
            "ON s.key = d.document || '_version' "
            "AND s.payload->>'version' = d.version "
            "ORDER BY document, section"
        ).fetchall()
    matches = []
    for row in rows:
        content = row["text"].lower()
        if all(term in content for term in terms):
            offset = max(0, content.index(terms[0]) - 60)
            matches.append(
                SectionMatch.model_validate(
                    {**row, "snippet": row["text"][offset : offset + 300]}
                )
            )
    return matches[:20]


def read(claim_id: str, run_id: UUID, request: SectionInput) -> SectionRead:
    """Record the exact section returned to an active scoped claim worker."""
    with connect() as connection:
        required(
            connection.execute(
                "SELECT id FROM claims WHERE id = %s FOR UPDATE", (claim_id,)
            ).fetchone(),
            "Claim",
        )
        active_run(connection, claim_id, run_id)
        section = required(
            connection.execute(
                "SELECT d.* FROM document_sections d JOIN settings s "
                "ON s.key = d.document || '_version' "
                "AND s.payload->>'version' = d.version "
                "WHERE document = %s AND section = %s",
                (request.document, request.section),
            ).fetchone(),
            "Section",
        )
        row = connection.execute(
            "INSERT INTO section_reads "
            "(claim_id, run_id, document, version, section, heading, text) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *",
            (
                claim_id,
                run_id,
                section["document"],
                section["version"],
                section["section"],
                section["heading"],
                section["text"],
            ),
        ).fetchone()
        return SectionRead.model_validate(row)


def reads(claim_id: str) -> list[SectionRead]:
    """Read only the evidence retrieved for this claim and its attempts."""
    with connect() as connection:
        required(
            connection.execute(
                "SELECT id FROM claims WHERE id = %s", (claim_id,)
            ).fetchone(),
            "Claim",
        )
        return [
            SectionRead.model_validate(row)
            for row in connection.execute(
                "SELECT * FROM section_reads WHERE claim_id = %s ORDER BY id",
                (claim_id,),
            ).fetchall()
        ]
