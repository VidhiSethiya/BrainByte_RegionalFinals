# TicketSphere — RAG & Data Layer

**Owner:** Shashank · **Tool:** Cursor · **Window:** ~8 of the 24 hours

This plan owns all retrieval, vector indexing, data stores and the domain data model.
**No changes to `backend/api.py` beyond what's in BLUEPRINT.md Phase 0.1.** All retrieval
logic lives in `backend/rag/`; all database schema in `backend/db/`. This is the
foundational layer — it must ship first so the other two teams can mock against it.

---

## Contract signatures

Vidhi/Naman call this signature; you implement it:

```python
# backend/rag/rag_retriever.py
def retrieve(
    query: str,
    user: dict,                    # {"id", "role", "clearances"}
    summary: str = "",
    filters: dict[str, str] = {},  # e.g. {"environment": "prod", "team": "aws"}
    decompose: bool = False,       # True means split query into subqueries
    top_k: int | None = None,      # defaults to settings.FINAL_TOP_K
) -> list[RetrievedChunk]:
    """
    Hybrid retrieval (vector + BM25) with ACL filtering and optional query decomposition.
    Returns scored chunks ordered by relevance. Never returns unauthorized content.
    """
```

Priyal calls this; you implement it:

```python
# backend/rag/rag_retriever.py — same retrieve() as above
# Used by the KB chatbot to ground long-context questions
```

SQLite models you define; both other teams import from `db.sqlite.models`:

```python
# db/sqlite/models.py
class Ticket(Base):
    # See BLUEPRINT.md §3 for the full schema
    id: str
    external_id: str
    title: str
    body_masked: str
    category: str
    severity: str          # "S1", "S2", "S3", "S4"
    priority_score: int    # 0–100
    assigned_team: str     # "ops", "azure", "aws", "gcp"
    status: str
    confidence: float
    needs_human: bool
    created_at: datetime
    # ... plus 5 more fields (see BLUEPRINT)

class TriageRun(Base):
    # Full decision + execution metadata
    ticket_id: str
    decision_json: dict    # Full TriageDecision serialised
    model: str
    tier: str              # "fast", "standard", "deep"
    tokens: int
    cost_usd: float
    latency_ms: int
    trace_id: str
    # ... plus audit fields
```

---

## Phases

### Phase 0 — Boot (0–1h)

| # | Task | Files | Done when |
|---|---|---|---|
| 0.1 | SQLite models: `User`, `Ticket`, `TriageRun`, `Document`, `ChatSession`, `ChatMessage` (reuse) | `db/sqlite/models.py` | `python db/inspect_db.py` shows all 8 tables |
| 0.2 | Chroma + embedding setup; `EMBEDDING_MODEL=text-embedding-3-large` in `.env` | `backend/rag/embeddings.py`, `config.py` | `test_embeddings.py` embeds 10 texts without error |
| 0.3 | Chunker with ticket/runbook separators; `CHUNK_SIZE=900`, `CHUNK_OVERLAP=150` | `backend/rag/chunker.py` | Chunker respects `\n## Symptom`, `\n## Diagnosis`, `\n## Fix` boundaries in test runbook |

### Phase 1 — Ingest & anonymisation (1–3h)

| # | Task | Files | Done when |
|---|---|---|---|
| 1.1 | PII patterns for domain: ticket IDs (INC0012345), error codes (ORA-, KB5-), AWS keys, Azure connection strings, JWTs | `backend/guardrails/pii.py` | Regex test suite passes: `INC0012345` never matches, `AKIA...` always does |
| 1.2 | Anonymizer: two-pass (regex + LLM), reversible masking with `[TYPE_N]` tokens | `backend/rag/anonymizer.py` | Integration test: mask, embed, unmask → original recoverable |
| 1.3 | Multimodal ingest: PDF text + pages as images, OCR on scanned pages | `backend/rag/multimodal.py` | `test_multimodal.py` extracts text and renders page 3 as an image |

### Phase 2 — Retrieval: vector + hybrid (3–6h)

| # | Task | Files | Done when |
|---|---|---|---|
| 2.1 | Vector retrieval: embed query, cosine search in Chroma, top-20 candidate scoring | `backend/rag/rag_retriever.py::_vector_search()` | Query "RDS failover" returns 20 chunks, top 1 has similarity ≥ 0.75 |
| 2.2 | BM25 indexing (in-process, rebuild on corpus change); RRF fusion with k=60 | `backend/rag/rag_retriever.py::_keyword_search()`, RRF merge | Query "INC0012345" keyword rank is ≤ 5 (exact match found), vector rank > 10 |
| 2.3 | Query rewrite: decompose multi-part questions into sub-queries via fast-tier model | `backend/rag/rag_retriever.py::_rewrite_query()` | Query "what changed since last week" decomposes into ≥2 sub-questions |
| 2.4 | CRAG grading: are retrieved chunks actually about this ticket? Optionally re-retrieve | `backend/rag/rag_retriever.py::_grade_chunks()` | Low-relevance candidates are filtered or re-retrieved once |

### Phase 3 — ACL & retrieval validation (6–8h)

| # | Task | Files | Done when |
|---|---|---|---|
| 3.1 | ACL in Chroma metadata: role-based flat keys `acl_ops: true`, sensitivity ceiling, team filtering | `backend/guardrails/governance/access_control.py`, `backend/rag/chunker.py` | `aws1` engineer never sees ops-only docs; manager sees all |
| 3.2 | Retrieval validation: defence in depth re-check after Chroma returns | `backend/rag/rag_retriever.py::_can_read()` | Sync test: pull a chunk that passed Chroma filtering, re-verify it passed ACL |
| 3.3 | Seed corpus generation: 500 synthetic tickets (4 teams × 8 categories × 4 severities) with gold labels | `db/vectordb/seed_vector_db.py --generate` | `python db/inspect_db.py --chunks 100` shows 400 indexed, gold labels in `tickets.true_*` columns |
| 3.4 | rag_indexer: ingest file/text, de-id, chunk, embed, write to Chroma + SQLite | `backend/rag/rag_indexer.py` | Upload a test ticket, `db/inspect_db.py` confirms chunk count matches |

### Phase 4 — Integration & retrieval eval (8–9h)

| # | Task | Files | Done when |
|---|---|---|---|
| 4.1 | Retrieval eval set: 12 held-out tickets, scored on vector vs hybrid, winner set in `.env` | `observability/evals.py` hybrid A/B | Both modes tested, scores recorded, loser removed from the run |
| 4.2 | Integration test: `Vidhi/Naman` call `retrieve(query, user)` with mocked agents | Mock in `backend/ai/agents.py` test file | Agent receives 6 chunks, no unauthorized content, citations have page numbers |

**Total estimated: 9h of 20.**

---

## File ownership

**You own:**
- `backend/rag/*.py` (all retrieval logic)
- `backend/guardrails/pii.py` (domain PII patterns)
- `backend/guardrails/governance/access_control.py` (ACL enforcement)
- `db/sqlite/models.py` (the seven relational tables)
- `db/vectordb/vector_store.py` (Chroma interface)
- `db/vectordb/seed_vector_db.py` (corpus generation)
- `db/inspect_db.py` (already exists, you maintain it)

**You do NOT touch:**
- `backend/api.py` (except Phase 0.1 config)
- `backend/ai/*` (Vidhi/Naman own this)
- `backend/chatbot/*` (Priyal owns this)
- `frontend/` (Trapti owns this)
- `backend/guardrails/input_guard.py`, `output_guard.py`, `validators.py` (Vidhi/Naman tune these)

**Shared cautiously:**
- `config.py` — you add `EMBEDDING_MODEL`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `RETRIEVAL_MODE` and `RERANK_*` here. Vidhi/Naman add `REASONING_MODEL`, etc. Merge conflict points: **coordinate in Phase 0**.

---

## Known risks

| Risk | Mitigation |
|---|---|
| Changing embeddings mid-build invalidates the index | Decide embedding model in Phase 0.2, then lock it. Reseed only once. |
| Two teams call `init_db()` and seed the corpus in parallel | Add a lock file. Shashank owns seedin protocol. |
| Vidhi/Naman forget to pass `user` to `retrieve()` | Write the function signature in a stub first; type checking catches the omission. |
| Chunker boundaries split a ticket ID or error code | Test the chunker against real ticket samples in Phase 1.3, not synthetic ones. |

---

## Jira integration

Create these stories on the board:

- **[SCRUM-xxx] RAG Layer - Phase 0: Schema & Setup**
- **[SCRUM-xxx] RAG Layer - Phase 1: Anonymisation**
- **[SCRUM-xxx] RAG Layer - Phase 2: Hybrid Retrieval**
- **[SCRUM-xxx] RAG Layer - Phase 3: ACL & Validation**
- **[SCRUM-xxx] RAG Layer - Phase 4: Integration**

Link them to the board under the RAG epic. Each phase is a story; tasks are the subtasks.

---

## Definition of done

- [ ] All `retrieve()` calls in the Vidhi/Naman test suite pass with no unauthorized content leaking
- [ ] Seed corpus generates without hanging or crashing
- [ ] `db/inspect_db.py` shows chunk count = document metadata count (consistency check passes)
- [ ] Hybrid A/B eval run completes; winner is set in `.env`
- [ ] No hard-coded Ollama endpoints in the retriever — all config via `settings.py`
- [ ] All file operations use `settings.VECTOR_DIR` etc, not hardcoded paths
