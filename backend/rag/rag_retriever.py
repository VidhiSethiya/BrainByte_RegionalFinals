"""Retrieval.

Two modes, chosen by `RETRIEVAL_MODE` in .env — this is a **build-day decision**, not
a code change:

  vector (default)   rewrite -> embed -> Chroma cosine search -> top-k
  hybrid             rewrite -> vector + BM25 -> RRF fusion -> [rerank] -> top-k

TicketSphere defaults to hybrid because the corpus carries exact identifiers
(INC…, ORA-…, HTTP 502, service names) that dense embeddings blur.

Access control is applied inside the vector query in both modes, never afterwards.
Defence-in-depth `can_read` still runs after Chroma returns.
"""

from __future__ import annotations

import re
import threading
from functools import lru_cache
from typing import Any

from ai.llm import chat_json, embed_query, parallel_map
from ai.prompts import QUERY_DECOMPOSE_PROMPT, QUERY_REWRITE_PROMPT
from config import settings
from db.vectordb import vector_store
from guardrails.governance.access_control import build_where, can_read
from observability.telemetry import log
from rag.schemas import ChunkGradeVerdict, Citation, GradeResult, RetrievedChunk

_TOKEN_RE = re.compile(r"[a-z0-9_./-]+")
_bm25_cache: dict[str, tuple[int, Any, list[dict]]] = {}
_bm25_lock = threading.Lock()

# Lives here (not ai/prompts.py) so the RAG layer owns CRAG without crossing team
# boundaries; agents may later move this constant into prompts.py.
CRAG_GRADE_PROMPT = """\
You are a retrieval grader for an IT ticket-intelligence system.
Given a ticket/query and retrieved evidence chunks, decide whether the chunks
are actually about this failure.

Return JSON only, matching this schema:
{{
  "action": "keep" | "filter" | "rewrite",
  "keep_labels": ["C1", "C2"],
  "rewrite_query": "optional better search query if action is rewrite",
  "reason": "short explanation"
}}

Rules:
- "keep" — most chunks are on-topic; keep_labels may be all of them.
- "filter" — drop off-topic chunks; keep_labels lists only the relevant ones.
- "rewrite" — evidence is mostly irrelevant; suggest one rewrite_query for a
  single re-retrieve. Do not invent facts.
- Prefer "filter" over "rewrite" when at least one chunk is useful.
- Ticket ids (INC…) and error codes in the query are strong relevance signals.

Query:
{query}

Chunks:
{chunks}
"""


def hybrid_enabled() -> bool:
    return settings.RETRIEVAL_MODE == "hybrid"


# --- query understanding ----------------------------------------------------


def rewrite_query(question: str, summary: str = "", trace=None) -> str:
    """Standalone-ify a follow-up. Falls back to the raw question on any failure."""
    if not summary.strip():
        return question
    result = chat_json(
        QUERY_REWRITE_PROMPT.format(summary=summary, question=question),
        fast=True,
        trace=trace,
        default={},
    )
    return ((result or {}).get("query") or "").strip() or question


def decompose_query(question: str, trace=None) -> list[str]:
    result = chat_json(
        QUERY_DECOMPOSE_PROMPT.format(question=question), fast=True, trace=trace, default={}
    )
    subs = [s.strip() for s in (result or {}).get("subqueries", []) if s and s.strip()]
    return subs[:3] or [question]


# --- retrievers -------------------------------------------------------------


def _vector_search(query: str, where: dict | None, top_k: int) -> list[dict]:
    try:
        return vector_store.query(embed_query(query), top_k=top_k, where=where)
    except Exception as exc:  # noqa: BLE001
        log.error("vector search failed: %s", exc)
        return []


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _get_bm25(where: dict | None):
    """Build (and cache) a BM25 index over the ACL-visible corpus.

    Cached per (corpus_version, ACL shape) so two users with different clearances get
    different indexes and a re-index invalidates both.
    """
    key = repr(where)
    version = vector_store.corpus_version()

    with _bm25_lock:
        cached = _bm25_cache.get(key)
        if cached and cached[0] == version:
            return cached[1], cached[2]

    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        log.warning("rank_bm25 not installed — keyword search unavailable")
        return None, []

    rows = vector_store.all_chunks(where=where)
    if not rows:
        return None, []

    index = BM25Okapi([_tokenize(r["text"]) for r in rows])
    with _bm25_lock:
        _bm25_cache[key] = (version, index, rows)
    return index, rows


def _keyword_search(query: str, where: dict | None, top_k: int) -> list[dict]:
    index, rows = _get_bm25(where)
    if index is None:
        return []
    scores = index.get_scores(_tokenize(query))
    ranked = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [
        {
            "id": rows[i]["id"],
            "text": rows[i]["text"],
            "metadata": rows[i]["metadata"],
            "score": float(scores[i]),
            "rank": rank + 1,
        }
        for rank, i in enumerate(ranked)
        if scores[i] > 0
    ]


# --- fusion + rerank (hybrid mode only) -------------------------------------


def reciprocal_rank_fusion(runs: list[list[dict]], k: int | None = None) -> list[dict]:
    """RRF: score = sum(1 / (k + rank)).

    Rank-based, so cosine similarity and BM25 scores never need to be normalised
    against each other — the reason this is the standard fusion for hybrid search.
    """
    k = k or settings.RRF_K
    fused: dict[str, dict] = {}

    for run_index, run in enumerate(runs):
        source = "vector_rank" if run_index % 2 == 0 else "keyword_rank"
        for hit in run:
            entry = fused.setdefault(
                hit["id"], {**hit, "score": 0.0, "vector_rank": None, "keyword_rank": None}
            )
            entry["score"] += 1.0 / (k + hit["rank"])
            if entry[source] is None or hit["rank"] < entry[source]:
                entry[source] = hit["rank"]

    return sorted(fused.values(), key=lambda h: h["score"], reverse=True)


@lru_cache(maxsize=1)
def _cross_encoder():
    """Loaded lazily — the import pulls torch, and the model is a ~90MB download."""
    if not settings.RERANK_ENABLED:
        return None
    try:
        from sentence_transformers import CrossEncoder

        log.info("loading reranker %s", settings.RERANK_MODEL)
        return CrossEncoder(settings.RERANK_MODEL, max_length=512)
    except Exception as exc:  # noqa: BLE001
        log.warning("reranker unavailable (%s) — using fusion order", exc)
        return None


def rerank(query: str, hits: list[dict], top_k: int) -> list[dict]:
    model = _cross_encoder()
    if model is None or not hits:
        return hits[:top_k]
    try:
        scores = model.predict([(query, h["text"][:2000]) for h in hits])
        for hit, score in zip(hits, scores):
            hit["rerank_score"] = float(score)
        return sorted(hits, key=lambda h: h["rerank_score"], reverse=True)[:top_k]
    except Exception as exc:  # noqa: BLE001
        log.warning("rerank failed (%s) — using fusion order", exc)
        return hits[:top_k]


# --- CRAG grading -----------------------------------------------------------


def grade_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    trace=None,
) -> GradeResult:
    """CRAG: keep / filter / rewrite. Does not re-retrieve — agents own that loop.

    Returns filtered chunks plus an optional rewrite_query hint for one retry.
    """
    if not chunks:
        return GradeResult(chunks=[], action="none", reason="no chunks to grade")

    rendered = "\n\n".join(
        f"[{c.label}] ({c.filename})\n{c.text[:1200]}" for c in chunks
    )
    raw = chat_json(
        CRAG_GRADE_PROMPT.format(query=query, chunks=rendered),
        fast=True,
        trace=trace,
        default={},
    ) or {}

    try:
        verdict = ChunkGradeVerdict.model_validate(raw)
    except Exception:  # noqa: BLE001
        log.warning("CRAG grade parse failed — keeping all chunks")
        return GradeResult(chunks=chunks, action="keep", reason="grade parse failed; kept all")

    if verdict.action == "rewrite":
        return GradeResult(
            chunks=chunks,
            action="rewrite",
            rewrite_query=(verdict.rewrite_query or "").strip() or None,
            reason=verdict.reason,
        )

    if verdict.action == "filter" and verdict.keep_labels:
        keep = {lbl.strip() for lbl in verdict.keep_labels}
        filtered = [c for c in chunks if c.label in keep]
        # Relabel for stable C1..Cn citation positions after filtering.
        for i, chunk in enumerate(filtered, start=1):
            chunk.metadata = {**chunk.metadata, "label": f"C{i}"}
        return GradeResult(
            chunks=filtered or chunks,
            action="filter",
            reason=verdict.reason,
        )

    return GradeResult(chunks=chunks, action="keep", reason=verdict.reason or "kept")


# --- entrypoint -------------------------------------------------------------


def retrieve(
    query: str,
    user: dict,
    summary: str = "",
    filters: dict[str, str] | None = None,
    top_k: int | None = None,
    decompose: bool = False,
    trace=None,
) -> list[RetrievedChunk]:
    """Retrieve for one query, scoped to what `user` may read.

    `filters` are Chroma metadata equality filters merged into the ACL `where`
    clause. TicketSphere keys: doc_type, team, service, environment, category,
    severity, resolved (string "true"/"false").

    First positional argument is `query` (contract name). Callers that still
    pass a bare positional string remain compatible.
    """
    top_k = top_k or settings.FINAL_TOP_K
    where = build_where(user, extra=filters)
    candidates = settings.RETRIEVE_TOP_K

    rewritten = rewrite_query(query, summary, trace=trace)
    queries = decompose_query(rewritten, trace=trace) if decompose else [rewritten]

    if hybrid_enabled():
        tasks: list[Any] = []
        for q in queries:
            tasks.append(lambda q=q: _vector_search(q, where, candidates))
            tasks.append(lambda q=q: _keyword_search(q, where, candidates))
        runs = [run or [] for run in parallel_map(lambda fn: fn(), tasks, seconds=90)]
        ranked = reciprocal_rank_fusion(runs)
    else:
        runs = [run or [] for run in parallel_map(lambda q: _vector_search(q, where, candidates), queries)]
        seen: dict[str, dict] = {}
        for run in runs:
            for hit in run:
                existing = seen.get(hit["id"])
                if existing is None or hit["score"] > existing["score"]:
                    seen[hit["id"]] = {**hit, "vector_rank": hit["rank"], "keyword_rank": None}
        ranked = sorted(seen.values(), key=lambda h: h["score"], reverse=True)

    # Defence in depth — the store already filtered; log any ACL miss as drift.
    allowed: list[dict] = []
    dropped = 0
    for h in ranked:
        if can_read(user, h.get("metadata", {})):
            allowed.append(h)
        else:
            dropped += 1
    if dropped:
        log.warning(
            "ACL defence-in-depth dropped %d chunk(s) that passed Chroma where",
            dropped,
        )
    ranked = allowed
    top = rerank(rewritten, ranked[: candidates * 2], top_k) if hybrid_enabled() else ranked[:top_k]

    chunks = []
    for position, hit in enumerate(top, start=1):
        meta = hit.get("metadata", {}) or {}
        chunks.append(
            RetrievedChunk(
                id=hit["id"],
                doc_id=meta.get("doc_id", ""),
                filename=meta.get("filename", "unknown"),
                text=hit["text"],
                page=int(meta.get("page") or 0) or None,
                score=round(float(hit.get("score", 0)), 6),
                vector_rank=hit.get("vector_rank"),
                keyword_rank=hit.get("keyword_rank"),
                rerank_score=hit.get("rerank_score"),
                metadata={**meta, "label": f"C{position}"},
            )
        )

    log.info(
        "retrieved %d chunks (%s mode) for %r",
        len(chunks),
        settings.RETRIEVAL_MODE,
        rewritten[:60],
    )
    return chunks


def build_context(chunks: list[RetrievedChunk]) -> str:
    """Render chunks for the prompt. Labels here must match the citation labels."""
    return "\n\n".join(
        f"[{c.label}] ({c.filename}{f', p.{c.page}' if c.page else ''})\n{c.text}" for c in chunks
    )


def to_citations(chunks: list[RetrievedChunk], answer: str = "") -> list[Citation]:
    """Return citations, keeping only labels the answer actually referenced."""
    used = set(re.findall(r"\[(C\d+)\]", answer)) if answer else None
    return [
        Citation(
            label=c.label,
            doc_id=c.doc_id,
            filename=c.filename,
            page=c.page,
            snippet=c.text[:300].strip(),
        )
        for c in chunks
        if used is None or c.label in used
    ]
