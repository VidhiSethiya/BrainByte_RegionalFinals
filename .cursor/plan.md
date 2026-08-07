# TicketSphere — Project Plan

**TicketSphere** — *An enterprise AI ticket intelligence platform*

Cursor's execution view of the same project Claude Code builds. `CLAUDE.md` is the
architecture contract; `.claude/plans/BLUEPRINT.md` is now the **authoritative roadmap**
and its phases supersede the generic tasks below. Frontend work is specified separately in
`frontend/FRONTEND_SPEC.md` and owned by Trapti in Windsurf — do not duplicate it here.

## Architecture summary

Enterprise multimodal RAG + agentic platform, applied to application-maintenance ticket
triage: ingest → classify → prioritise → route → human gate → sync back to Jira.

```
Client → api.py (JWT → rate limit → validate → query params)
       → guardrails.input_guard   (injection, policy, PII detect+mask)
       → rag.rag_retriever        (rewrite → vector search → ACL filter → top-k)
       → ai.agents                (LangGraph: plan → retrieve → synthesise → verify)
       → guardrails.output_guard  (PII leak, groundedness, policy, JSON validate)
       → guardrails.governance    (hash-chained immutable audit log)
       → observability.telemetry  (latency, tokens, cost, trace)
       → Client
```

## Stack

| Component | Choice |
|---|---|
| Backend | Python 3.12 + Flask (all routes in `backend/api.py`) |
| Frontend | Vite + React 19 + TypeScript + Ant Design |
| Server state | TanStack Query · Charts: Recharts |
| Auth | JWT (PyJWT), users in SQLite via SQLAlchemy |
| LLM / embeddings | `langchain_openai` (`ChatOpenAI`, `OpenAIEmbeddings`) — never raw `openai`/`ollama` SDKs |
| LLM runtime | Local Ollama `http://localhost:11434/v1`, hosted endpoint as opt-in with auto-fallback |
| Models | `llama-3.2-3b-it:latest` chat · `gte-large:latest` embeddings |
| Orchestration | LangGraph |
| Vector DB | Chroma, persistent at `db/vectordb/data/chroma` |
| Retrieval | **Vector search by default.** Hybrid (BM25 + RRF + rerank) is built but off — `RETRIEVAL_MODE` in `.env` |
| Documents | PyMuPDF (PDF text + page images), Pillow |

Single origin: Flask serves `frontend/dist`; in dev Vite proxies `/api` to
`127.0.0.1:5000`. No CORS configuration anywhere. TLS verification is disabled by
default (`DISABLE_SSL_VERIFY=true`).

## Layout

```
backend/                  # application logic only — no persistence code
  run.py config.py
  api.py                  # ALL routes + envelope + pagination/sort/filter/search
                          # + rate limit + JWT. No shared "utils" package.
  rag/                    schemas chunker embeddings rag_indexer rag_retriever
                          anonymizer multimodal
  ai/                     llm (clients + with_timeout + parallel_map) prompts agents
  chatbot/                conversation_manager memory_manager context_manager
                          session_manager
  guardrails/             input_guard output_guard pii validators
    governance/           access_control audit
  observability/          telemetry evals

db/                       # both persistence layers, kept apart
  inspect_db.py           # reads both + consistency check
  sqlite/     models.py   data/app.db
  vectordb/   vector_store.py seed_vector_db.py   data/chroma/ uploads/ seed/

frontend/src/             main App layouts/ pages/ components/ api/client.ts
docs/                     FLOW.md JUDGES_QA.md
```

**Two stores.** `from db.sqlite.models import ...` for relational data,
`from db.vectordb import vector_store` for Chroma. Nothing in `backend/` may reach a
store any other way. Delete `db/sqlite/data/` and `db/vectordb/data/` to reset.

## Commands

```bash
ollama serve
cd backend && pip install -r requirements.txt && cp .env.example .env && python run.py
cd frontend && npm install && npm run dev
python db/vectordb/seed_vector_db.py --reset
python db/inspect_db.py
```

---

## Master Task List

Pre-build placeholder-filling. Replaced by the blueprint's phases on build day.

### Phase 0 — Environment

- [ ] **TASK-001**: Verify local stack boots
  - **Files**: none (verification only)
  - **Acceptance Criteria**: `ollama list` shows `llama-3.2-3b-it` and `gte-large`;
    `python run.py` starts and `GET /api/health` returns 200 with
    `provider: "local"`; `npm run dev` serves the login page; `admin`/`admin123` signs in
  - **Status**: PENDING

- [ ] **TASK-002**: Seed the corpus
  - **Files**: `db/vectordb/data/seed/*`
  - **Acceptance Criteria**: real documents in `db/vectordb/data/seed/`;
    `python db/vectordb/seed_vector_db.py --reset` reports chunks > 0; the Knowledge Base
    page lists them; re-running does not duplicate chunks
  - **Status**: PENDING

### Phase 1 — Domain fill (after the problem statement lands)

- [ ] **TASK-003**: Domain schemas
  - **Files**: `backend/rag/schemas.py`
  - **Acceptance Criteria**: `AnonymizedRecord` and `GeneratedReport` renamed to the
    real entities with real fields; no `[PLACEHOLDER]` left in the file
  - **Status**: PENDING

- [ ] **TASK-004**: Domain prompts and persona
  - **Files**: `backend/ai/prompts.py`
  - **Acceptance Criteria**: `SYSTEM_PERSONA`, `ANSWER_PROMPT`, `POLICY_CHECK_PROMPT`
    carry the real domain, personas and compliance rules; no bracketed placeholders
  - **Status**: PENDING

- [ ] **TASK-005**: Domain PII patterns
  - **Files**: `backend/guardrails/pii.py`
  - **Acceptance Criteria**: `PATTERNS` includes the identifiers this domain carries;
    a sample document masks them; `has_leak` catches them in an answer
  - **Status**: PENDING

- [ ] **TASK-006**: Roles and sensitivity model
  - **Files**: `backend/guardrails/governance/access_control.py`, `backend/config.py`, `db/sqlite/models.py`
  - **Acceptance Criteria**: real role set; a restricted user's `/api/search` omits
    documents above their ceiling; an admin sees them
  - **Status**: PENDING

- [ ] **TASK-007**: Retrieval mode decision
  - **Files**: `backend/.env`, `backend/config.py`
  - **Acceptance Criteria**: eval set run under `RETRIEVAL_MODE=vector` and `=hybrid`;
    numbers recorded in `docs/JUDGES_QA.md`; the winner set in `.env` with a one-line
    rationale
  - **Status**: PENDING

- [ ] **TASK-008**: Eval set
  - **Files**: `backend/observability/evals.py`
  - **Acceptance Criteria**: 8–12 real questions including ≥2 that must be refused;
    `POST /api/evals/run` populates the Evaluations tab with non-zero metrics
  - **Status**: PENDING

- [ ] **TASK-009**: Guardrail thresholds
  - **Files**: `backend/guardrails/output_guard.py`, `backend/guardrails/input_guard.py`
  - **Acceptance Criteria**: `GROUNDEDNESS_FLOOR` / `GROUNDEDNESS_REFUSE` tuned against
    the eval set with the rationale in a comment; an unanswerable question is refused,
    a valid one is not
  - **Status**: PENDING

- [ ] **TASK-010**: Docs refresh
  - **Files**: `docs/FLOW.md`, `docs/JUDGES_QA.md`
  - **Acceptance Criteria**: domain sections filled, real measured numbers pasted in,
    no `[PLACEHOLDER]` tokens left
  - **Status**: PENDING
