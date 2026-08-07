"""Ingest pipeline: load -> anonymise -> chunk -> embed -> upsert -> register.

One entrypoint (`index_document`) used by both the upload API and the seed script, so
there is exactly one definition of what "indexed" means.

`index_ticket` is the TicketSphere path: ticket JSON/text → masked body → chunks with
`doc_type=ticket_history` metadata → Chroma + SQLite Document mirror.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from db.sqlite.models import Document, SessionLocal
from db.vectordb import vector_store
from guardrails.governance import audit
from observability.telemetry import log
from rag.anonymizer import anonymize_document
from rag.chunker import chunk_document
from rag.embeddings import embed_documents
from rag.multimodal import load_file, load_text
from rag.schemas import RAGDocument, Ticket, TicketIngestRequest


def index_document(
    doc: RAGDocument,
    user_id: str | None = None,
    anonymize: bool = True,
) -> dict:
    """Index one document. Returns a summary dict for the API response."""
    doc.id = doc.id or uuid.uuid4().hex

    if anonymize:
        doc, token_map = anonymize_document(doc)
        redacted = len(token_map)
    else:
        redacted = 0

    chunks = chunk_document(doc)
    if not chunks:
        _register(doc, user_id, chunk_count=0, status="failed")
        return {"doc_id": doc.id, "chunks": 0, "status": "failed", "reason": "no text extracted"}

    vectors = embed_documents([c.text for c in chunks])
    vector_store.upsert(chunks, vectors)
    _register(doc, user_id, chunk_count=len(chunks), status="indexed")

    audit.record(
        "document.indexed",
        user_id=user_id,
        resource=doc.id,
        filename=doc.filename,
        modality=doc.modality,
        chunks=len(chunks),
        pii_tokens_redacted=redacted,
        sensitivity=doc.sensitivity,
    )
    log.info("indexed %s -> %d chunks (%d PII tokens masked)", doc.filename, len(chunks), redacted)

    return {
        "doc_id": doc.id,
        "filename": doc.filename,
        "chunks": len(chunks),
        "pii_tokens_redacted": redacted,
        "status": "indexed",
    }


def index_ticket(
    ticket: Ticket | TicketIngestRequest | dict[str, Any],
    user_id: str | None = None,
    *,
    anonymize: bool = True,
    allowed_roles: list[str] | None = None,
    sensitivity: str = "confidential",
    resolved: bool = False,
    resolution_minutes: int | None = None,
    category: str = "",
    severity: str = "",
    team: str = "",
    service: str = "",
) -> dict:
    """Index one ticket into Chroma as `doc_type=ticket_history`.

    Does not write the operational SQLite `tickets` row — that table is owned by
    the data-layer Executioner task. This only fills the vector + Document mirror
    so agents can call `similar_tickets` / `kb_search` immediately.
    """
    parsed = _coerce_ticket(ticket)
    title = parsed.title or "untitled"
    external_id = parsed.external_id or parsed.id
    body = parsed.body_masked

    team_tag = (team or str(parsed.raw.get("team") or "")).strip()
    roles = allowed_roles if allowed_roles is not None else (
        [team_tag] if team_tag else ["admin", "manager"]
    )
    svc = service or parsed.application

    attrs: dict[str, Any] = {
        "doc_type": "ticket_history",
        "external_id": external_id,
        "source": parsed.source,
        "title": title,
        "application": parsed.application,
        "environment": str(parsed.environment),
        "channel": parsed.channel,
        "team": team_tag,
        "service": svc,
        "category": category,
        "severity": severity,
        "resolved": "true" if resolved else "false",
    }
    if resolution_minutes is not None:
        attrs["resolution_minutes"] = str(resolution_minutes)
    if parsed.attachments:
        attrs["attachments"] = ",".join(parsed.attachments)

    doc = RAGDocument(
        id=parsed.id or uuid.uuid4().hex,
        filename=f"{external_id or parsed.id}.ticket.txt",
        text=_ticket_text(title=title, body=body, external_id=external_id, ticket=parsed),
        modality="text",
        source=f"ticket:{parsed.source}:{external_id}",
        allowed_roles=roles,
        sensitivity=sensitivity,  # type: ignore[arg-type]
        attributes=attrs,
    )

    result = index_document(doc, user_id=user_id, anonymize=anonymize)
    result["external_id"] = external_id
    result["doc_type"] = "ticket_history"
    return result


def index_file(path: str | Path, user_id: str | None = None, **doc_kwargs) -> dict:
    return index_document(load_file(path, **doc_kwargs), user_id=user_id)


def index_text(filename: str, text: str, user_id: str | None = None, **doc_kwargs) -> dict:
    return index_document(load_text(filename, text, **doc_kwargs), user_id=user_id)


def delete_document(doc_id: str, user_id: str | None = None) -> int:
    removed = vector_store.delete_document(doc_id)
    with SessionLocal() as s:
        record = s.get(Document, doc_id)
        if record:
            s.delete(record)
            s.commit()
    audit.record("document.deleted", user_id=user_id, resource=doc_id, chunks_removed=removed)
    return removed


def _coerce_ticket(ticket: Ticket | TicketIngestRequest | dict[str, Any]) -> Ticket:
    if isinstance(ticket, Ticket):
        return ticket
    if isinstance(ticket, TicketIngestRequest):
        return Ticket(
            id=uuid.uuid4().hex,
            external_id=ticket.external_id or "",
            source=ticket.source,
            title=ticket.title,
            body_masked=ticket.body,
            application=ticket.application,
            environment=ticket.environment,
            channel=ticket.channel,
            attachments=list(ticket.attachments),
            raw=dict(ticket.raw),
            reporter_token=ticket.reporter,
        )
    data = dict(ticket)
    source = data.get("source") or "manual"
    if source not in ("jira", "synthetic", "manual"):
        source = "manual"
    return Ticket(
        id=str(data.get("id") or uuid.uuid4().hex),
        external_id=str(data.get("external_id") or ""),
        source=source,  # type: ignore[arg-type]
        title=str(data.get("title") or ""),
        body_masked=str(data.get("body_masked") or data.get("body") or ""),
        reporter_token=str(data.get("reporter_token") or data.get("reporter") or ""),
        application=str(data.get("application") or ""),
        environment=data.get("environment") or "prod",  # type: ignore[arg-type]
        channel=str(data.get("channel") or ""),
        attachments=list(data.get("attachments") or []),
        raw=dict(data.get("raw") or {}),
        tokens_replaced=dict(data.get("tokens_replaced") or {}),
    )


def _ticket_text(*, title: str, body: str, external_id: str, ticket: Ticket) -> str:
    """Canonical sectioned layout so the chunker separators fire cleanly."""
    parts = [
        f"Ticket: {external_id}" if external_id else "Ticket",
        f"Title: {title}",
    ]
    if ticket.application:
        parts.append(f"Application: {ticket.application}")
    if ticket.environment:
        parts.append(f"Environment\n{ticket.environment}")
    parts.extend(["", "Summary", title, "", "Description", body.strip()])
    return "\n".join(parts)


def _register(doc: RAGDocument, user_id: str | None, chunk_count: int, status: str) -> None:
    """Mirror the document into SQLite so the admin UI can list it without querying
    the vector store."""
    with SessionLocal() as s:
        existing = s.get(Document, doc.id)
        if existing:
            existing.chunk_count = chunk_count
            existing.status = status
        else:
            s.add(
                Document(
                    id=doc.id,
                    filename=doc.filename,
                    modality=doc.modality,
                    source=doc.source,
                    allowed_roles=doc.allowed_roles,
                    sensitivity=doc.sensitivity,
                    attributes=doc.attributes,
                    chunk_count=chunk_count,
                    status=status,
                    uploaded_by=user_id,
                )
            )
        s.commit()
