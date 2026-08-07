# System Flow

One page, PPT-ready. Each step is one slide's worth of content.

**Product:** TicketSphere — An enterprise AI ticket intelligence platform
**Domain:** Application maintenance / IT service management ·
**Users:** platform engineers working a team queue (Ops / Azure / AWS / GCP), and support
managers overseeing all four, approving escalations and querying ticket history

---

## The pipeline in one line

```
Raw data → Ingest & de-identify → Retrieval → Governed AI layer → Grounded answer + dashboard
```

---

## Step 1 — Ingest

**What happens.** Documents arrive by upload or seed script. Text, PDF and images are all
accepted. PDF pages with almost no extractable text are rendered and read by a vision
model, so scans and diagrams do not enter the index as empty chunks.

**Then.** Two-pass de-identification: deterministic regex catches structured identifiers
(email, phone, card, national IDs); an LLM pass catches contextual ones (names, orgs).
Identifiers become stable tokens — `[PERSON_1]` is the same person everywhere — so the
text stays semantically useful after masking.

**Output.** Chunks of ~900 chars with 150 overlap, each carrying page number, source
file, sensitivity level and the roles allowed to see it.

`backend/rag/multimodal.py · anonymizer.py · chunker.py`

---

## Step 2 — Index

**What happens.** Chunks are embedded with `gte-large` (1024-dim) and written to Chroma
with their governance metadata attached, under `db/vectordb/data/chroma`.

`backend/rag/embeddings.py · rag_indexer.py · db/vectordb/vector_store.py`

---

## The two data stores

There are **two databases, not three.** Chat sessions live in the SQLite one. They sit
in their own top-level package, one folder each, so it is obvious at a glance which is
which:

```
db/
  inspect_db.py              read both at once, and check they agree
  sqlite/
    models.py                tables, engine, session factory
    data/app.db              the file itself
  vectordb/
    vector_store.py          the only code that talks to Chroma
    seed_vector_db.py        bulk-load the corpus
    data/chroma/             the index itself
    data/seed/               documents waiting to be indexed
    data/uploads/            files received through the API
```

| Store | Where | What it holds |
|---|---|---|
| **SQLite** (via SQLAlchemy) | `db/sqlite/data/app.db` | `users`, `chat_sessions`, `chat_messages`, `documents`, `audit_log`, `feedback`, `eval_results` |
| **Chroma** | `db/vectordb/data/chroma/` | chunk text + its embedding vector + governance metadata |

All seven relational tables — including passwords and every chat message — sit in that
one SQLite file, defined in `db/sqlite/models.py`.

**Nothing in `backend/` touches a store directly.** It goes through
`from db.sqlite.models import ...` or `from db.vectordb import vector_store`. That is
what makes "swap Chroma for pgvector" a one-package change rather than a search across
the codebase.

### Why two, in plain terms

They answer completely different questions.

**SQLite answers "which exact rows, in what order?"** — show me page 3 of documents
sorted by date, count how many answers were blocked today, find this user by username.
Exact lookups, sorting, counting, joining. That is what a relational database is for.

**Chroma answers "what text means roughly the same as this?"** — give me the six chunks
closest in meaning to this question. It stores each chunk as a 1024-number vector and
searches by distance between vectors, using a special index (HNSW) that makes that fast.

Putting chat history in a vector database would mean no reliable ordering and no joins —
you cannot ask "the last six messages in this session" of a similarity search. Putting
embeddings in SQLite would mean comparing the query against **every** stored vector one
by one on every question, which gets slow immediately.

> **Judge question you should expect:** "why not one database?" The honest answer is
> that **pgvector** (Postgres with a vector extension) does both well, and is the right
> migration if this ever needed a document row and its embeddings to be updated in one
> transaction. We used two because at this size the operational simplicity wins, and
> `vector_store.py` is the only module touching the vector side — so that migration is
> one file.

### The one thing that looks like duplication but isn't

`documents` exists in **both** stores, on purpose:

- **SQLite** holds the *governance record*: filename, sensitivity, which roles may see
  it, chunk count, who uploaded it, when. This is what the Knowledge Base table
  paginates, sorts and filters — no vector search involved, so listing documents never
  touches Chroma.
- **Chroma** holds the *content*: the actual chunks and their vectors.

`rag_indexer.py` `_register()` writes the SQLite record every time it indexes, and
`delete_document()` removes from both. They are kept in step in one place.

### A file that will confuse you

Inside `db/vectordb/data/chroma/` you will find a file called **`chroma.sqlite3`** plus
some `.bin` files. That is **Chroma's own internal storage** — it happens to use SQLite
under the hood — and it is *not* a third database you manage. Never open or edit it
directly; go through `db/vectordb/vector_store.py`.

### Resetting

Delete `db/sqlite/data/` and `db/vectordb/data/` and everything goes: users, chat
history, audit trail, uploads and vectors. Then re-run
`python db/vectordb/seed_vector_db.py --reset` and log in again as `admin` / `admin123`
(recreated automatically on boot).

Dropping just one is also useful: delete `db/sqlite/data/` to clear chat history and the
audit trail while keeping the indexed corpus, or `db/vectordb/data/chroma/` to re-index
without losing users. That independence is a side benefit of keeping them apart.

---

## Step 3 — Request & authentication

**What happens.** Every call carries a JWT. The token's role and clearances determine
what the user can retrieve, not just what they can see. Requests are rate-limited,
validated against a Pydantic schema, and given a trace ID.

**One origin.** Flask serves the built frontend and the API from the same host, so no
CORS configuration exists anywhere in the project.

`backend/api.py` — every route, plus the pagination/rate-limit/auth plumbing

---

## Step 4 — Input guardrails

**What happens.** Before retrieval: length check → regex prompt-injection signatures →
PII detect and mask → (only if ambiguous) an LLM injection classifier.

**Why this order.** The deterministic checks cost microseconds and cannot hallucinate.
The model call is the exception, not the default, so the median request pays nothing.

`backend/guardrails/input_guard.py · pii.py`

---

## Step 5 — Retrieval

**Default path (`RETRIEVAL_MODE=vector`).**

1. **Rewrite** — the follow-up is made standalone using the conversation summary
2. **Vector search** — embed the query, cosine search in Chroma, ACL applied *inside*
   the query
3. **Top-k** — 6 chunks go to the model

**Optional path (`RETRIEVAL_MODE=hybrid`)** adds a BM25 keyword run, fuses both with
RRF (`1/(k+rank)`, so two incomparable score scales merge without normalisation), and
can rerank the shortlist with a cross-encoder.

**Which one.** A build-day decision, made by running the eval set both ways — not a
code change. Vector search is the default because it has one failure mode and is
usually enough on prose. Hybrid earns its cost when the corpus carries **exact
identifiers** — contract numbers, SKUs, error codes — that dense embeddings blur.

**Access control.** The ACL is a Chroma `where` clause, not a post-filter — unauthorised
text never reaches the prompt, and top-k does not silently degrade for restricted users.

`backend/rag/rag_retriever.py · guardrails/governance/access_control.py`

---

## Step 6 — AI layer

**What happens.** A LangGraph graph runs `plan → retrieve → generate → verify`. Plan
decides whether the knowledge base is needed at all. If verify finds the answer
ungrounded, the graph routes back to retrieval **once** with a decomposed query — a bad
first query is the usual cause, and a retry fixes it more often than regenerating.

**Context assembly.** Under a fixed budget, priority is: persona → question → retrieved
context → summary → history. Evidence outranks history, because an ungrounded answer is
worse than a forgetful one.

`backend/ai/agents.py · chatbot/context_manager.py · ai/prompts.py`

---

## Step 7 — Output guardrails

**What happens.** Shape check → PII leak scan and redaction → groundedness score and
policy check (run in parallel, one round-trip).

**Thresholds.** Below 0.25 grounded the answer is refused outright. Between 0.25 and 0.5
it ships with a visible caveat. A policy violation blocks regardless of score.

`backend/guardrails/output_guard.py · validators.py`

---

## Step 8 — Memory & conversation

**What happens.** Short-term memory replays the last 6 messages verbatim. Long-term
memory is a rolling LLM summary refreshed every 6 turns. The summary is also what makes
follow-up questions searchable in step 5 — it is retrieval infrastructure, not chat
polish. The assistant proposes three grounded follow-up questions after each answer.

`backend/chatbot/*`

---

## Step 9 — Governance & observability

**What happens.** Every login, retrieval, block, answer, upload and deletion is written
to a hash-chained append-only audit log — each entry hashes the previous one, so any
edit breaks the chain and `verify_chain()` names the first bad row. Traces record
per-stage latency, tokens and cost.

`backend/guardrails/governance/audit.py · observability/telemetry.py`

---

## Step 10 — Delivery

**What the user sees.**

| Screen | Shows |
|---|---|
| Assistant | Answer, inline citations with page numbers, groundedness %, latency, tokens, 👍/👎 |
| Chatbot drawer | Single-session knowledge-base Q&A, reachable from every page |
| Dashboard | Requests, p95 latency, token spend, error rate, per-turn charts, expandable traces |
| Knowledge Base | Server-side paginated table, upload with role + sensitivity, PII-masked count |
| Evaluations | Groundedness, context precision/recall, hallucination rate, per-question detail |
| Audit Trail | Every action, hash chain verification |

Two chat surfaces on purpose: `/api/chat` is multi-session for the Assistant page;
`/api/chatbot` is a **single server-pinned session** so the widget's memory and rolling
summary build across the whole demo instead of resetting per question.

Feedback is queued for human-in-the-loop review, where a reviewer can supply a corrected
answer.

`frontend/src/pages/* · components/ChatbotDrawer.tsx`

---

## What makes this defensible

1. **Retrieval strategy is measured, not assumed** — vector and hybrid both implemented,
   the choice made by running the eval set, switchable by one env variable
2. **Governance is architectural** — ACL enforced at query time, not filtered afterwards
3. **Guardrails on both sides** — injection in, PII and hallucination out
4. **Evals are shipped, not claimed** — a dashboard tab with real numbers
5. **Runs fully offline** — local Ollama, no vendor dependency, no data leaving the box
6. **Every answer is auditable** — hash-chained log, per-stage traces, page-level citations

**What TicketSphere adds on top of that platform**

7. **Ten-node triage graph with a corrective loop** — normalise → enrich → grade →
   classify → assess → route → reflect → verify → gate → sync. Handoffs are validated
   typed objects, never prose, and both retry loops are capped at one so no unbounded
   loop is reachable.
8. **The LLM never counts** — aggregate questions ("how many S1 this week") are answered
   by a deterministic SQL tool and only narrated by the model
9. **Nothing acts without a human** — S1 and low-confidence decisions are gated for
   approval, the only write tool refuses unapproved decisions, and the system recommends
   a first action but never executes one

---

## Appendix — Looking inside the two stores

Not slide material. This is for debugging during the build and for answering "show me"
if a judge asks. Run everything from the **repo root** with the backend venv active.

> Stop the Flask server before writing to either store from a script. Reading while it
> runs is fine — both stores allow multiple readers.

### Both at once — the built-in inspector

```bash
python db/inspect_db.py
```

Prints every SQLite table with row counts and a sample of rows, then the Chroma chunk
count with sample chunks, then a **consistency check** — the `documents` table and
Chroma must agree on chunk counts per document.

```bash
python db/inspect_db.py --rows 10 --chunks 20
python db/inspect_db.py --sql "select username, role from users"
```

Read-only, safe to run while the server is up. A `DRIFT` line in the consistency check
means an index run failed halfway — re-upload that document, or rebuild everything with
`python db/vectordb/seed_vector_db.py --reset`.

### SQLite — `db/sqlite/data/app.db`

For clicking around rather than querying:

- **[DB Browser for SQLite](https://sqlitebrowser.org)** — free, opens the file
  directly, "Browse Data" shows every table with no SQL needed. The easiest option.
- **PyCharm** — Database tool window → **+** → Data Source → SQLite → pick
  `db/sqlite/data/app.db`. *(Professional only; Community does not ship database tools.)*

Worth checking while building:

| Question | Query for `--sql` |
|---|---|
| Who can log in? | `select username, role, clearances from users` |
| Did the upload register? | `select filename, chunk_count, status from documents` |
| What got blocked? | `select action, resource, created_at from audit_log where action like '%blocked%'` |
| Is the chatbot's pinned session there? | `select id, title from chat_sessions where title = 'Knowledge Base Assistant'` |

Passwords are salted hashes (Werkzeug), so `password_hash` is meaningless to read —
that is correct behaviour, not a bug.

### Chroma — `db/vectordb/data/chroma/`

**Chroma has no GUI.** Use the inspector above, or the running app — which is the better
option in front of a judge, because it shows the real path rather than a debug dump:

| What you want to see | How |
|---|---|
| How many chunks are indexed | `GET /api/health` → `indexed_chunks`, also in the header badge |
| Which documents exist | Knowledge Base page, or `GET /api/documents` |
| What retrieval actually returns | `POST /api/search` — each chunk with `score`, `vector_rank`, `keyword_rank`, `rerank_score` |
| Which chunks produced an answer | The citation tags under any assistant reply |

`POST /api/search` is the one to demo: it shows the retrieval layer's working, not just
its output.
