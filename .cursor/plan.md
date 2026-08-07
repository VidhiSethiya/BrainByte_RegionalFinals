# TicketSphere — RAG Layer Execution Plan

Source of truth: `.cursor/BLUEPRINT.md` · Design: `.cursor/rag.md`  
Orchestrator maintains this file. Executioner takes one PENDING task. Verifier marks DONE.

---

## Phase 0 — Boot

- [x] **TASK-RAG-0.1**: Domain config (ROLES/TEAMS/hybrid/embeddings)
  - **Files**: `backend/config.py`, `backend/.env.example`
  - **Acceptance Criteria**: `RETRIEVAL_MODE` defaults to hybrid; `EMBEDDING_MODEL` is `azure/genailab-maas-text-embedding-3-large`; `ROLES`/`TEAMS` match BLUEPRINT
  - **Status**: DONE

- [x] **TASK-RAG-0.2**: SQLite `tickets` + `triage_runs` + demo users
  - **Files**: `db/sqlite/models.py`
  - **Acceptance Criteria**: `python db/inspect_db.py` lists tickets/triage_runs; admin/manager/ops1/azure1/aws1/gcp1 seeded
  - **Status**: DONE

- [x] **TASK-RAG-0.3**: Chunker domain separators
  - **Files**: `backend/rag/chunker.py`
  - **Acceptance Criteria**: Separators include `## Fix`, Environment, Logs, Resolution, `--- ticket`
  - **Status**: DONE

- [x] **TASK-RAG-0.4**: Domain Pydantic schemas
  - **Files**: `backend/rag/schemas.py`
  - **Acceptance Criteria**: `Ticket`, `TriageDecision`, verdicts, `TicketStats`, `GradeResult` defined only here
  - **Status**: DONE

## Phase 1 — Ingest & anonymisation

- [x] **TASK-RAG-1.1**: Domain PII + secret patterns
  - **Files**: `backend/guardrails/pii.py`
  - **Acceptance Criteria**: `AKIA…` masked/redacted; `INC0012345` never matched; secrets in `LEAK_TYPES`; PHONE requires separators
  - **Status**: DONE

- [x] **TASK-RAG-1.2**: Anonymizer → Ticket
  - **Files**: `backend/rag/anonymizer.py`
  - **Acceptance Criteria**: `anonymize_record` returns `Ticket`; secrets wiped before mask; `LLM_PASS_MIN_CHARS=120`
  - **Status**: DONE

- [x] **TASK-RAG-1.3**: Multimodal settings-only vision
  - **Files**: `backend/rag/multimodal.py`
  - **Acceptance Criteria**: Vision path reads `settings.VISION_MODEL` only
  - **Status**: DONE

## Phase 2 — Hybrid retrieval + CRAG

- [x] **TASK-RAG-2.1**: `retrieve(query=…)` contract
  - **Files**: `backend/rag/rag_retriever.py`
  - **Acceptance Criteria**: First arg named `query`; filters documented; positional callers still work
  - **Status**: DONE

- [x] **TASK-RAG-2.2**: Hybrid path ready (BM25+RRF)
  - **Files**: `backend/rag/rag_retriever.py`, `backend/config.py`
  - **Acceptance Criteria**: `RETRIEVAL_MODE=hybrid` enables vector+BM25+RRF; verify after seed via `run_retrieval_ab`
  - **Status**: DONE

- [x] **TASK-RAG-2.3**: `grade_chunks` CRAG
  - **Files**: `backend/rag/rag_retriever.py`, `backend/rag/schemas.py`
  - **Acceptance Criteria**: Returns `GradeResult` with keep/filter/rewrite; no self-loop
  - **Status**: DONE

- [ ] **TASK-RAG-2.4**: Semantic cache (optional / deferred)
  - **Files**: `backend/rag/rag_retriever.py`
  - **Acceptance Criteria**: Near-duplicate ticket returns in <1s
  - **Status**: PENDING (deferred — not on critical path)

## Phase 3 — ACL, indexer, seed

- [x] **TASK-RAG-3.1**: Sensitivity matrix + team ACL keys
  - **Files**: `backend/guardrails/governance/access_control.py`
  - **Acceptance Criteria**: admin/manager→restricted, engineer→confidential, viewer→internal; clearances map to `acl_<team>`
  - **Status**: DONE

- [x] **TASK-RAG-3.2**: ACL defence-in-depth logging
  - **Files**: `backend/rag/rag_retriever.py`, `backend/guardrails/governance/access_control.py`
  - **Acceptance Criteria**: Post-Chroma `can_read` + sensitivity check; drops logged
  - **Status**: DONE

- [x] **TASK-RAG-3.3**: `index_ticket()`
  - **Files**: `backend/rag/rag_indexer.py`
  - **Acceptance Criteria**: Indexes with `doc_type=ticket_history` + team ACL attrs
  - **Status**: DONE

- [x] **TASK-RAG-3.4**: Seed `--generate`
  - **Files**: `db/vectordb/seed_vector_db.py`
  - **Acceptance Criteria**: `--generate` writes 500 tickets (400 JSON + 100 held-out gold in SQLite), runbooks, catalogue, SLA, escalation
  - **Status**: DONE (generator + corpus files exist; **full Chroma embed deferred**)

- [ ] **TASK-RAG-3.5**: Reseed against locked embedding model
  - **Files**: `db/vectordb/seed_vector_db.py` (run)
  - **Acceptance Criteria**: `python db/vectordb/seed_vector_db.py --reset --generate` completes; `inspect_db` consistency OK
  - **Status**: DEFERRED — run **after** basic flow (Jira ingest → triage → retrieve) works end-to-end; do not block agents/integrations on this

## Phase 4 — Eval & handoff

- [x] **TASK-RAG-4.1**: Retrieval A/B harness
  - **Files**: `backend/observability/evals.py`, `docs/JUDGES_QA.md`
  - **Acceptance Criteria**: `run_retrieval_ab()` compares vector vs hybrid; JUDGES_QA documents shipped mode=hybrid and table for measured scores
  - **Status**: DONE (harness ready; **measured numbers after seed** — same deferral as 3.5)

- [x] **TASK-RAG-4.2**: Handoff contracts
  - **Files**: `.cursor/plan.md` (this file)
  - **Acceptance Criteria**: Agents import `retrieve`, `grade_chunks` from `rag.rag_retriever`; `Ticket`/`TriageDecision` from `rag.schemas`; SQL `Ticket`/`TriageRun` from `db.sqlite.models`
  - **Status**: DONE

---

## Handoff imports (for agents / chatbot)

```python
from rag.rag_retriever import retrieve, grade_chunks, build_context, to_citations
from rag.schemas import Ticket, TriageDecision, TicketIngestRequest, GradeResult, RetrievedChunk
from rag.rag_indexer import index_ticket, index_document
from db.sqlite.models import Ticket as TicketRow, TriageRun, SessionLocal
```

Demo users: `admin/admin123`, `manager/manager123`, `ops1/ops123`, `azure1/azure123`, `aws1/aws123`, `gcp1/gcp123`.

**Full flow + Jira plug-in contract for Claude / integrations team:**  
[`.claude/plans/rag-handoff.md`](../.claude/plans/rag-handoff.md)
