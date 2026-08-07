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
  - **Acceptance Criteria**: admin/manager→restricted, engineer→confidential; clearances map to `acl_<team>`
  - **Status**: DONE
  - **Note**: `viewer` removed from role model (2026-08-07) — see TASK-ROLE-1

- [x] **TASK-ROLE-1**: Drop `viewer` role
  - **Files**: `backend/config.py`, `backend/guardrails/governance/access_control.py`, `db/sqlite/models.py`, `backend/api.py`, `frontend/src/pages/Documents.tsx`, `.cursor/BLUEPRINT.md`
  - **Acceptance Criteria**: `ROLES` is admin/manager/engineer only; no `viewer` in MAX_SENSITIVITY; JWT/User defaults fall back to `engineer`
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

---

## Phase J — Jira sync + write-back (LLM + rulebook)

Source: `.claude/plans/BLUEPRINT.md` §7 · agents: `.claude/plans/llm.md` · handoff: `.claude/plans/rag-handoff.md`  
**Orchestrator (2026-08-07):** Phase J orchestrated. Live site verified via Atlassian MCP.  
**Do not re-implement** adapters/poller/triage that already exist — fill residuals only.

### MCP lock-in (brainbytes.atlassian.net)

| Fact | Value |
|---|---|
| Site / cloudId | `https://brainbytes.atlassian.net` / `3975e197-7e5f-47ad-9d2c-1046a1f39d6c` |
| Project | **`SCRUM`** (TicketSphere, next-gen Software) — not `INC` |
| Scopes | `read:jira-work`, `write:jira-work` |
| Transitions | To Do / In Progress / In Review / Done |
| Custom triage fields | **Absent** — write-back uses Priority + labels `ticketsphere-severity-*` / `ticketsphere-team-*` + comment; optional `JIRA_FIELD_*` if added later |
| Sample incident | `SCRUM-5` (P1 Azure AKS) etc. |

### Decision flow (what gets written to Jira)

```
Jira issue created/updated
  → poll (primary) or webhook (demo/curl)
  → upsert TicketRow (source=jira, external_id=key)
  → index_ticket()
  → triage graph: classify → assess(severity/priority vs SLA rulebook)
                 → route(team + capacity) → recommend first action (similar_tickets + runbooks)
                 → reflect → verify → gate
  → if auto-approve (S3/S4 + confidence ≥ 0.85) OR manager approve
       → ticket_update: Priority+labels (+ optional CF) + comment(rationale+citations) + transition
  → else park in human queue; audit always
```

### Tasks — Verifier lock (re-verify 2026-08-07 15:22)

- [x] **TASK-JIRA-1**: TicketSource ABC + config — **residual only**
  - **Files**: `backend/.env.example` *(only — ABC + `config.py` JIRA_* already present)*
  - **Acceptance Criteria**: `.env.example` documents `TICKET_SOURCE`, `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY=SCRUM`, `JIRA_POLL_SECONDS`, optional `JIRA_FIELD_*`; no other files changed
  - **Status**: DONE
  - **Verifier:** PASS

- [x] **TASK-JIRA-2**: Jira REST v3 adapter (Free Cloud)
  - **Files**: `backend/integrations/jira.py`
  - **Acceptance Criteria**: Basic auth; `fetch_since` JQL on `SCRUM`; update maps severity→Priority + labels; comment ADF; transitions; 429 backoff
  - **Status**: DONE
  - **Verifier (re-verify 2026-08-07):** PASS — Basic auth; fetch_since; update/comment/transition; 429 retry via FIX-B

- [x] **TASK-JIRA-3**: Synthetic adapter (offline demo)
  - **Files**: `backend/integrations/synthetic.py`
  - **Acceptance Criteria**: Same ABC; seed JSON; no network
  - **Status**: DONE
  - **Verifier:** PASS

- [x] **TASK-JIRA-4**: Poller + webhook ingest
  - **Files**: `backend/api.py`, `backend/integrations/poller.py`
  - **Acceptance Criteria**: Poll + watermark; upsert `(source, external_id)`; `POST /api/integrations/webhook` curl-demoable; dead-letter path (`sync_attempts` incremented)
  - **Status**: DONE
  - **Verifier (re-verify 2026-08-07):** PASS — poll/webhook/upsert present; dead-letter writes `sync_attempts` (FIX-D)

- [x] **TASK-JIRA-5**: Triage → fields (LLM + rulebook)
  - **Files**: `backend/ai/agents.py`, `backend/ai/prompts.py`, `backend/ai/tools.py`
  - **Acceptance Criteria**: `triage_assess` / `triage_route` / first-action; valid `TriageDecision`; `from ai.agents import ingest_and_triage` succeeds
  - **Status**: DONE
  - **Verifier (re-verify):** PASS — `create_app()` OK; `ingest_and_triage` / `triage_assess` / `triage_route` import; `TriageDecision` + `suggested_first_action` in `triage_sync`

- [x] **TASK-JIRA-6**: Gate + approved write-back
  - **Files**: `backend/ai/agents.py`, `backend/ai/tools.py`, `backend/api.py`
  - **Acceptance Criteria**: `ticket_update` gate; approve/override routes; audit; adapter calls use Jira key (`external_id`), never SQLite UUID
  - **Status**: DONE
  - **Verifier (re-verify):** PASS — `source.update(external_id)`; approve/auto-approve use `external_id`; audit on deny/execute/approve

- [x] **TASK-JIRA-7**: Role-scoped queues & dashboards (API)
  - **Files**: `backend/api.py` only
  - **Acceptance Criteria**:
    1. `GET /api/teams/queue` remains auth-scoped via `_scope_ticket_query` (verify; do not break)
    2. Add **`GET /api/analytics/triage`** with `@require_role("admin", "manager")` — engineers get **403**
    3. Response envelope `{"data": …, "meta": …}`; payload matches frontend `TriageAnalytics` in `frontend/src/api/client.ts` (at least `by_severity`, `by_team`, `sla_at_risk`, `awaiting_approval`; fill other numeric fields with real SQLite aggregates or `0` so Control/Evals do not crash)
    4. Counts come from SQLite `Ticket` / `TriageRun` — no LLM, no browser-side summing
  - **Status**: DONE
  - **Verifier (2026-08-07):** PASS — queue still scoped; manager/admin 200 with `by_severity`/`by_team`/…; engineer 403; SQLite-only; `{"data","meta"}` envelope

### Phase J status

**Complete.** JIRA-1 … JIRA-7 all DONE (including FIX-A…D residuals).

### Handoff order (updated)

1. ~~Phase J~~ DONE  
2. Orchestrator: next blueprint phase (outside JIRA-7)  
