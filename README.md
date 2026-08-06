# Enterprise Multimodal RAG + Agentic Platform

A pre-built skeleton for an enterprise AI application. Architecture, layers and
contracts are fixed; the domain logic is filled in from a problem statement on build
day.

- **What it does and how** → [docs/FLOW.md](docs/FLOW.md)
- **Technical Q&A prep** → [docs/JUDGES_QA.md](docs/JUDGES_QA.md)
- **Rules for Claude Code** → [CLAUDE.md](CLAUDE.md)
- **Rules for Cursor** → [.cursor/plan.md](.cursor/plan.md) and `.cursor/rules/`

## Quick start

```bash
ollama serve && ollama pull llama-3.2-3b-it:latest && ollama pull gte-large:latest
```

```bash
cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && copy .env.example .env && python run.py
```

```bash
cd frontend && npm install && npm run dev
```

Drop documents in `db/vectordb/data/seed/`, then from the repo root:

```bash
python db/vectordb/seed_vector_db.py --reset
```

Sign in at http://localhost:5173 with `admin` / `admin123`.

Backend and frontend share one origin — Flask serves `frontend/dist` in production, Vite
proxies `/api` in development — so there is no CORS setup.

## Storage

Two stores, one package each under `db/`:

| Package | Path | Holds |
|---|---|---|
| `db.sqlite.models` | `db/sqlite/data/app.db` | users, chat sessions and messages, documents, audit log, feedback, evals |
| `db.vectordb.vector_store` | `db/vectordb/data/chroma/` | chunk text + embeddings + governance metadata |

```bash
python db/inspect_db.py     # read both, plus a consistency check
```

Delete `db/sqlite/data/` and `db/vectordb/data/` to reset the demo. Full reasoning in
[docs/FLOW.md](docs/FLOW.md#the-two-data-stores).

## Retrieval

Ships on **vector search**. Hybrid (BM25 + RRF + optional cross-encoder rerank) is
implemented and switched on with `RETRIEVAL_MODE=hybrid` in `backend/.env` — no code
change. Decide on build day by running the eval set both ways; hybrid pays off when the
corpus carries exact identifiers that embeddings blur.

## On build day

In plan mode, hand the problem statement to the `guide-me` skill. It proposes
domain-specific enhancements, waits for your selection, then writes
`.claude/plans/BLUEPRINT.md` — a phased 20-hour roadmap. Mirror its phases into
`.cursor/plan.md` so both tools build the same thing.
