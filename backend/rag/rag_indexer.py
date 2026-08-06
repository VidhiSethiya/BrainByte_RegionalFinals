"""Ingest pipeline: load -> anonymise -> chunk -> embed -> upsert -> register.

One entrypoint (`index_document`) used by both the upload API and the seed script, so
there is exactly one definition of what "indexed" means.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from db.sqlite.models import Document, SessionLocal
from db.vectordb import vector_store
from guardrails.governance import audit
from observability.telemetry import log
from rag.anonymizer import anonymize_document
from rag.chunker import chunk_document
from rag.embeddings import embed_documents
from rag.multimodal import load_file, load_text
from rag.schemas import RAGDocument


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
