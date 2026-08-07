# TicketSphere

**An enterprise AI ticket intelligence platform.**

Application-maintenance ticket triage as a multi-agent system. A ticket arrives — from
Jira or the API — and TicketSphere normalises it, masks the PII and secrets inside it,
retrieves precedent from resolved tickets and team runbooks, classifies it, scores its
severity against the SLA matrix, routes it to the owning team, critiques its own decision,
runs it through output guardrails, and either syncs it back or parks it for a human.

Every decision is cited, costed, audited and reversible in two clicks.

---

## What it is built on

An enterprise multimodal RAG + agentic platform: Flask + LangGraph + Chroma + SQLite
behind a Vite/React/Ant Design console. Architecture, layer boundaries and contracts are
fixed in [`CLAUDE.md`](CLAUDE.md) — read that before changing anything.

| Concern | Choice |
|---|---|
| Orchestration | LangGraph — a graph, because `verify` and `grade` route backwards |
| Retrieval | Hybrid: dense + BM25, fused with RRF. Ticket corpora are identifier-heavy. |
| Models | Three tiers on the LiteLLM gateway, local Ollama as automatic fallback |
| Stores | Chroma for meaning, SQLite for rows — see [`docs/FLOW.md`](docs/FLOW.md) |
| Guardrails | Injection in, PII/secret and hallucination out, on every request |
| Governance | Chunk-level ACL inside the query, hash-chained audit log |

---

## Quickstart

```bash
ollama serve
```

```bash
cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && copy .env.example .env && python run.py
```

```bash
cd frontend && npm install && npm run dev
```

Backend on `http://127.0.0.1:5000`, frontend on `http://localhost:5173` which proxies
`/api` to it — one origin, so there is no CORS configuration anywhere in this project.

Seed the corpus, from the repo root with the backend venv active:

```bash
python db/vectordb/seed_vector_db.py --reset
```

Look inside both stores — tables, chunks, and a consistency check between them:

```bash
python db/inspect_db.py
```

Demo logins: `manager / manager123` (manager console), `aws1 / aws123` and the other three
team accounts (team console), `admin / admin123` (platform).

Reset everything: delete `db/sqlite/data/` and `db/vectordb/data/`, then re-seed.

---

## Documentation

| Doc | What it is |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | The architecture contract. Golden rules, layer boundaries, conventions. |
| [`.claude/plans/BLUEPRINT.md`](.claude/plans/BLUEPRINT.md) | The build plan — domain model, agent design, model choices, roadmap, demo script. |
| [`frontend/FRONTEND_SPEC.md`](frontend/FRONTEND_SPEC.md) | The frontend contract — design brief, API types, per-screen specs. |
| [`docs/FLOW.md`](docs/FLOW.md) | How a request moves through the system, step by step. |
| [`docs/JUDGES_QA.md`](docs/JUDGES_QA.md) | Technical Q&A — the reasoning behind each choice, and its limits. |

## A note on the data

Every ticket in this repo is **synthetic**. No real customer data, no real incident
records, no production identifiers. The corpus is generated with deliberate realism —
typos, half-pasted stack traces, duplicate reports of one outage, and planted secrets that
exercise the redaction path — because a triage system tested only on clean input is not
tested.
