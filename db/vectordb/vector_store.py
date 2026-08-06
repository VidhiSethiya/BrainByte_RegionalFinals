"""Chroma CRUD — the only module that talks to the vector database.

Persistent local client under db/vectordb/data/chroma. Embeddings are supplied
explicitly (we never let Chroma call an embedding function of its own) so the model
choice stays in backend/ai/llm.py.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import chromadb

from config import settings
from observability.telemetry import log
from rag.schemas import Chunk

_client: chromadb.ClientAPI | None = None
_lock = threading.Lock()

# Bumped on every write so the keyword index knows to rebuild.
_version = 0


def _coerce_metadata(metadata: dict[str, Any] | None) -> dict[str, str | int | float | bool]:
    """Chroma metadata values must be scalars.

    Lists become JSON strings and anything else is stringified, so a document
    attribute added on build day can never blow up an upsert.
    """
    if not metadata:
        return {}
    safe: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            safe[key] = value
        elif isinstance(value, (list, tuple)):
            safe[key] = json.dumps(list(value))
        else:
            safe[key] = str(value)
    return safe


def _collection():
    global _client
    if _client is None:
        settings.ensure_dirs()
        _client = chromadb.PersistentClient(path=str(settings.CHROMA_PERSIST_DIR))
    return _client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def corpus_version() -> int:
    return _version


def upsert(chunks: list[Chunk], vectors: list[list[float]]) -> int:
    if not chunks:
        return 0
    if len(chunks) != len(vectors):
        raise ValueError("chunks and vectors must be the same length")

    global _version
    col = _collection()
    with _lock:
        col.upsert(
            ids=[c.id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=vectors,
            metadatas=[_coerce_metadata(c.metadata) for c in chunks],
        )
        _version += 1
    log.info("upserted %d chunks into %s", len(chunks), settings.CHROMA_COLLECTION)
    return len(chunks)


def query(vector: list[float], top_k: int, where: dict[str, Any] | None = None) -> list[dict]:
    """Vector similarity search.

    `where` is applied *inside* Chroma — access control must never be a post-filter.
    An empty collection or empty vector returns [] rather than raising.
    """
    col = _collection()
    count = col.count()
    if count == 0 or not vector:
        return []

    result = col.query(
        query_embeddings=[vector],
        n_results=min(top_k, count),
        where=where or None,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]
    for rank, (cid, text, meta, dist) in enumerate(zip(ids, docs, metas, dists)):
        hits.append(
            {
                "id": cid,
                "text": text or "",
                "metadata": meta or {},
                "score": 1.0 - float(dist),  # cosine distance -> similarity
                "rank": rank + 1,
            }
        )
    return hits


def all_chunks(where: dict[str, Any] | None = None) -> list[dict]:
    """Full corpus dump — used to build the BM25 keyword index in hybrid mode."""
    col = _collection()
    if col.count() == 0:
        return []
    result = col.get(where=where or None, include=["documents", "metadatas"])
    return [
        {"id": cid, "text": text or "", "metadata": meta or {}}
        for cid, text, meta in zip(
            result.get("ids") or [],
            result.get("documents") or [],
            result.get("metadatas") or [],
        )
    ]


def delete_document(doc_id: str) -> int:
    """Remove every chunk belonging to a document. Idempotent."""
    if not doc_id:
        return 0
    global _version
    col = _collection()
    with _lock:
        existing = col.get(where={"doc_id": doc_id}, include=[])
        ids = existing.get("ids") or []
        if ids:
            col.delete(ids=ids)
            _version += 1
    return len(ids)


def count() -> int:
    return _collection().count()


def reset() -> None:
    """Drop the whole collection. Used by the seed script's --reset."""
    global _version
    _collection()  # ensure the client exists
    with _lock:
        try:
            _client.delete_collection(settings.CHROMA_COLLECTION)
        except Exception:  # noqa: BLE001 - collection may not exist yet
            pass
        _version += 1
