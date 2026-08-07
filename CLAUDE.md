# CLAUDE.md

Enterprise multimodal RAG + agentic platform. This repo is a **pre-built skeleton**:
architecture, layers and contracts are fixed; the domain-specific logic is filled in
on build day from a problem statement via the `guide-me` skill.

A teammate works in Cursor against `.cursor/rules/*` and `.cursor/plan.md`, which
mirror this file. If you change a rule here, change it there.

## Golden rules

1. **Do not restructure.** The layer boundaries below are the product story. Add files
   inside a layer; never move responsibilities between layers.
2. **Fill placeholders, don't add files.** Anything marked `[PLACEHOLDER: ...]` or
   `[UPPERCASE_IN_BRACKETS]` is meant to be replaced. Prefer editing an existing module
   over creating a new one. No file exists unless it is imported by something.
3. **No test suite.** This project intentionally ships no tests. Verify by running the
   app. Do not create `tests/`, pytest config, or CI files.
4. **Budget is 20 coding hours.** Reject scope that does not survive a demo. If a change
   takes >45 min and isn't on the blueprint's critical path, say so before starting.
5. **Every LLM call goes through `backend/ai/llm.py`.** Never import `openai`, `ollama`,
   or instantiate a client anywhere else.

## Commands

```bash
# Local LLM runtime (must be running before the backend)
ollama serve
ollama pull llama-3.2-3b-it:latest
ollama pull gte-large:latest

# Backend (from backend/)
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
copy .env.example .env
python run.py                                       # http://127.0.0.1:5000

# Frontend (from frontend/)
npm install
npm run dev                                         # http://localhost:5173
npm run build                                       # Flask then serves it at :5000

# Seed the vector DB (repo root, backend venv active)
python db/vectordb/seed_vector_db.py --reset

# Look inside both stores — tables, chunks, and a SQLite/Chroma consistency check
python db/inspect_db.py
```

Demo login: `admin` / `admin123`.

## Stack (fixed — do not substitute)

| Layer | Choice |
|---|---|
| Python | 3.12 |
| Frontend | Vite + React 19 + TypeScript + Ant Design |
| Frontend state | TanStack Query (server state), Zustand (UI state only) |
| Charts | Recharts |
| Backend | Flask — every route in `api.py` |
| Auth | JWT (PyJWT), users in SQLite via SQLAlchemy |
| LLM + embeddings client | `langchain_openai` — `ChatOpenAI`, `OpenAIEmbeddings` |
| LLM runtime | Local Ollama by default; hosted endpoint opt-in with auto-fallback |
| Orchestration | LangGraph for multi-step/multi-agent flows |
| Vector DB | Chroma, persistent at `db/vectordb/data/chroma` |
| Retrieval | **Vector search by default**; hybrid is built but off (see below) |
| Documents | PyMuPDF (PDF text + page images), Pillow (images) |
| Validation | Pydantic v2 for every request body and every LLM JSON output |

## Retrieval mode — a build-day decision

`RETRIEVAL_MODE` in `.env` selects it. Both paths are implemented in
`rag/rag_retriever.py`; **no code change is needed to switch.**

- `vector` (default) — embed the query, cosine search in Chroma, top-k. One failure
  mode, fast, and on prose corpora usually enough.
- `hybrid` — vector + BM25 keyword, fused with RRF, optionally cross-encoder reranked.

Choose `hybrid` only if the corpus carries **exact identifiers** — contract numbers,
SKUs, error codes, policy IDs — that dense embeddings blur. Decide by running the eval
set both ways on build day and keeping the winner. Do not default to hybrid because it
sounds more advanced; an unjustified extra index is a liability under time pressure.

## Same-origin by construction

Flask serves `frontend/dist`; in development Vite proxies `/api` to `127.0.0.1:5000`.
The browser only ever sees one origin, so **there is no CORS configuration in this
project** — do not add `flask-cors`. If you hit a cross-origin error, the fix is to
route through the proxy, not to relax headers.

TLS verification is disabled by default (`DISABLE_SSL_VERIFY=true`) via a shared
`httpx` client in `ai/llm.py`. Local Ollama is plain http, and TLS-inspecting corporate
proxies otherwise break hosted endpoints mid-demo.

## Request flow (do not deviate)

```
Client → api.py (JWT auth → rate limit → Pydantic validate → query params)
       → guardrails.input_guard      (injection, policy, PII detect+mask)
       → rag.rag_retriever           (rewrite → search → ACL filter → top-k)
       → ai.agents                   (LangGraph: plan → retrieve → synthesise → verify)
       → guardrails.output_guard     (PII leak, groundedness, policy, JSON validate)
       → guardrails.governance.audit (hash-chained immutable log)
       → observability.telemetry     (latency, tokens, cost, trace)
       → Client
```

Skipping a stage is a bug, even for "simple" endpoints. Audit and telemetry are
non-optional on every request that touches an LLM.

## Layout

```
backend/                     # application logic only — no persistence code
  run.py config.py
  api.py        # ALL routes + response envelope + pagination/sort/filter/search
                # + rate limiting + JWT. There is no shared "utils" package.
  rag/          schemas chunker embeddings rag_indexer rag_retriever
                anonymizer multimodal
  ai/           llm (clients, with_timeout, parallel_map) prompts agents
  chatbot/      conversation_manager memory_manager context_manager session_manager
  guardrails/   input_guard output_guard pii validators
    governance/ access_control audit
  observability/ telemetry evals

db/                          # both persistence layers, kept apart
  inspect_db.py              # reads both, plus a consistency check
  sqlite/    models.py       # SQLAlchemy models, engine, SessionLocal, init_db
             data/app.db
  vectordb/  vector_store.py seed_vector_db.py
             data/chroma/ uploads/ seed/

frontend/src/   main App layouts/ pages/ components/ api/client.ts
docs/           FLOW.md JUDGES_QA.md
```

**Two stores, kept in separate packages.** `db.sqlite.models` holds all seven relational
tables — users, chat sessions, chat messages, documents, audit log, feedback, evals.
`db.vectordb.vector_store` is the only module that talks to Chroma. `documents` appears
in both on purpose: SQLite carries the governance record so the Knowledge Base table can
paginate without touching the vector store, Chroma carries the content.
`rag_indexer._register()` keeps them in step. Full explanation in `docs/FLOW.md`.

Import them as `from db.sqlite.models import User, SessionLocal` and
`from db.vectordb import vector_store`. Nothing in `backend/` may talk to a store any
other way. `db/` sits at the repo root, so `run.py` and the two scripts put the root on
`sys.path`; `db/__init__.py` then adds `backend/` so the packages can read `config`.

Delete `db/sqlite/data/` and `db/vectordb/data/` to reset the entire demo state.

## Conventions

**Python**
- Pydantic models live in `rag/schemas.py` only. Import them; don't redefine shapes.
- Every route returns `{"data": ..., "meta": {...}}` on success and
  `{"error": {"code": str, "message": str}}` on failure. Never a bare list.
- List endpoints accept `page`, `page_size`, `sort`, `order`, `q`, `filter[...]` and
  return `meta.total`, `meta.page`, `meta.page_size`. Use the helpers already in
  `api.py` — do not hand-roll pagination.
- Any external/LLM call: wrap in `with_timeout` from `ai/llm.py`. Fan-out work uses
  `parallel_map` from the same module, never a bare `ThreadPoolExecutor`.
- Config is read from `config.py` only. No `os.getenv` outside that file.
- Log with `observability/telemetry.py`, not `print`.

**TypeScript**
- All HTTP goes through `src/api/client.ts`. No `fetch` in components.
- Server data uses TanStack Query. Zustand holds UI state (filters, drawer open) only.
- Ant Design components only — no custom CSS frameworks, no Tailwind, no styled-components.
- Tables are AntD `<Table>` in **server-side** mode wired to the list-endpoint contract.

**Visual design**
- The design language is locked:
  `.claude/skills/guide-me/references/design-system.md`. Read it before writing any UI.
- Applied through the AntD `ConfigProvider` theme in `main.tsx`, **not** a stylesheet —
  CSS variables do not restyle AntD components.
- No hard-coded hex, radius, or font-family in a component file. Light mode only.

**Prompts**
- All prompt text lives in `ai/prompts.py` as named constants. No inline f-string
  prompts in business logic. Every prompt that expects JSON must state the schema and
  be validated by `guardrails/validators.py`.

## Two chat surfaces

- `POST /api/chat` — full pipeline, **multi-session**. The Assistant page. Caller
  supplies `session_id` or a new session is created.
- `POST /api/chatbot` — same pipeline, **single session**. The drawer widget available
  on every page. The server pins one thread per user and ignores any `session_id` the
  client sends, so its memory and rolling summary accumulate across the whole demo.

## Non-negotiable safety surface

These exist because enterprise judges ask about them. Never remove or stub them out to
save time; keep them shallow instead:

- Input guardrails: prompt-injection filtering, policy check, PII detect → mask
- Output guardrails: PII leak scan, groundedness/hallucination check, JSON validation
- Chunk-level access control: enforced in the retriever via Chroma metadata `where`,
  never filtered in the route handler after the fact
- Immutable audit log: hash-chained, append-only
- Evals: groundedness, context precision/recall, hallucination rate — surfaced in the UI

  ## add these according to the problem statement
  01     Structured Output Agent
Enforce Pydantic JSON schemas, validate tool responses, retry on parse errors, log validation failures.
→ SHOWS  You can make LLMs reliable, not random.
BUILD IT  pydantic.dev/articles/llm-intro
  02     RAG Agent with Citation Grounding
Retrieve context, generate answers with sources, flag low-confidence responses, fallback to search.
→ SHOWS  You can prevent hallucinations at scale.
BUILD IT  js.langchain.com/docs/how_to/qa_citations
  03     ReAct Planning Agent
Observe → think → act → reflect loop, max iteration limits, self-critique, graceful degradation.
→ SHOWS  You can build agents that don't infinite loop.
BUILD IT  github.com/langchain-ai/react-agent
  04     Multi-Tool Orchestrator Agent
Dynamic tool registry, capability-based routing, permission scoping, parallel execution, conflict resolution.
→ SHOWS  You can coordinate complex workflows.
BUILD IT  docs.langchain.com/oss/python/langchain/multi-agent/subagents-personal-assistant
  05     Memory-Enabled Conversational Agent
Short-term buffer + long-term vector recall, context compression, relevance scoring, cross-session sync.
→ SHOWS  You can build agents that remember users.
BUILD IT  github.com/FareedKhan-dev/langgraph-long-memory
  06     Human-in-the-Loop Approval Agent
Uncertainty detection → pause → request human input → resume with validated context, full audit trail.
→ SHOWS  You can build safe, compliant systems.
BUILD IT  docs.bswen.com/blog/2026-04-16-langgraph-human-in-the-loop
  07     Cost-Aware Agent Router
Token budgeting per task, model routing by complexity/cost, early exit on confidence, cost-per-decision analytics.
→ SHOWS  You can reduce infra costs by 40–60%.
BUILD IT  docs.litellm.ai/docs/routing-load-balancing
  08     Event-Triggered Automation Agent
Listen to webhooks/queues, execute workflows on triggers, idempotent execution, dead-letter handling, retry logic.
→ SHOWS  You can build production automation, not demos.
BUILD IT  hookdeck.com/webhooks/guides/dead-letter-queues-webhook-reliability
  09     Multi-Agent Debate System
Multiple agents propose solutions, critic evaluates, voting/consensus logic, aggregator synthesizes with confidence.
→ SHOWS  You can orchestrate swarms, not single agents.
BUILD IT  github.com/composable-models/llm_multiagent_debate
  10     Self-Reflective Agent with Auto-Eval
Execute → evaluate via LLM-as-judge → critique reasoning → regenerate with constraints, log improvement metrics.
→ SHOWS  You can build systems that improve over time.
BUILD IT  github.com/noahshinn/reflexion
  11     Production Agent with Observability
Deploy with LangSmith/Arize tracing, latency/cost dashboards, alerting on loops/failures, canary testing, rollback.
→ SHOWS  You can ship to production, not just localhost.
BUILD IT  freecodecamp.org/news/how-to-trace-and-monitor-ai-agents-with-langsmith
  12     Open Source Agent Framework Contribution
Extend LangGraph/CrewAI/AutoGen with a new pattern, write docs + demo, publish benchmarks, submit PR + tutorial.
→ SHOWS  You're a community builder, not just a consumer.
BUILD IT  github.com/langchain-ai/langgraph/blob/main/CONTRIBUTING.m

## On build day

Run the `guide-me` skill with the problem statement. It proposes domain-specific
add-ons, waits for selection, then writes `.claude/plans/BLUEPRINT.md`. Build strictly
in that blueprint's phase order, and keep `.cursor/plan.md` in sync for the Cursor
teammate. Keep `docs/FLOW.md` and `docs/JUDGES_QA.md` updated as implementation lands —
they are the pitch deck and the Q&A prep.
