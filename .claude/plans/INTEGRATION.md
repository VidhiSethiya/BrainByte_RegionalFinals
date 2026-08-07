# TicketSphere — Three-Person Backend Integration

**Shashank (RAG/DB)** · **Priyal (Chatbot)** · **Vidhi & Naman (LLM/Agents/Jira)**

This document defines the boundaries and synchronization points so three teams can work in
parallel with minimal merge conflicts. **Read this before reading the individual plans.**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  FRONTEND (Trapti)                           │
│          Login → Queue / History / Triage / Control          │
└────────────────┬────────────────────────────────────────────┘
                 │
         ┌───────┴────────────────────────────────────────────────┐
         │  backend/api.py (Vidhi/Naman wire all endpoints)       │
         └───────┬──────────────────┬──────────────┬─────────────┘
                 │                  │              │
        ┌────────▼──────┐  ┌────────▼────┐  ┌─────▼──────────┐
        │ /chat          │  │ /chatbot     │  │ /tickets       │
        │ /sessions      │  │ /chatbot/... │  │ /teams/queue   │
        │ (multi)        │  │ (single)     │  │ /triage        │
        └────────┬──────┘  └────────┬────┘  └─────┬──────────┘
                 │                  │              │
        ┌────────▼──────────────────▼──────┐  ┌───▼──────────┐
        │  Priyal's handle_message()       │  │ Vidhi/Naman's│
        │  (Chatbot Layer)                 │  │ run_turn()   │
        └────────┬───────────────┬─────────┘  └───┬──────────┘
                 │               │                │
        ┌────────▼────┐  ┌───────▼──────┐  ┌─────▼──────────┐
        │ Shashank's  │  │ Shashank's   │  │ Vidhi/Naman's  │
        │ retrieve()  │  │ retrieve()   │  │ tools.py       │
        │ (KB Q&A)    │  │ (Triage)     │  │ (Ticket Sync)  │
        └────────┬────┘  └───────┬──────┘  └─────┬──────────┘
                 │               │                │
        ┌────────▼───────────────▼────────────────▼─────────┐
        │  Shashank's Chroma + SQLite (Data Layer)          │
        │  retrieve() with ACL + Chunker + Embedder        │
        └──────────────────────────────────────────────────┘
```

**Three main flows:**

1. **Knowledge-base Q&A** — Vidhi/Naman wire `/chat` + `/chatbot` → call Priyal's
   `handle_message()` → Priyal calls Shashank's `retrieve()` → answer cited
2. **Ticket triage** — Vidhi/Naman wire `/tickets` → call `run_turn()` → calls Shashank's
   `retrieve()` → calls `tools.py` (includes Jira sync)
3. **Shared infrastructure** — All three read from SQLite models; Vidhi/Naman wire all
   routes in `api.py`

---

## File ownership matrix

| File | Owner | Can read | Touches in which phase |
|---|---|---|---|
| `config.py` | Shashank | All | Ph0 (coordination needed) |
| `db/sqlite/models.py` | Shashank | All | Ph0 |
| `db/vectordb/*` | Shashank | All | Ph0–3 |
| `backend/rag/*` | Shashank | Vidhi/Naman/Priyal read | Ph0–4 |
| `backend/guardrails/pii.py` | Shashank | Vidhi/Naman tune | Ph0–3 |
| `backend/guardrails/access_control.py` | Shashank | Vidhi/Naman read | Ph0–1 |
| `backend/chatbot/*` | Priyal | Vidhi/Naman read | Ph1–4 |
| `backend/ai/*` | Vidhi/Naman | Priyal reads agents | Ph0–4 |
| `backend/ai/prompts.py` | Vidhi/Naman | — | Ph0 (frozen) |
| `backend/integrations/*` | Vidhi/Naman | — | Ph2–4 |
| `backend/guardrails/input_guard.py` | Vidhi/Naman | Shashank reads | Ph3 |
| `backend/guardrails/output_guard.py` | Vidhi/Naman | — | Ph3 |
| `backend/guardrails/validators.py` | Vidhi/Naman | — | Ph3 |
| `backend/api.py` | Vidhi/Naman | Priyal reads (doesn't edit) | Ph4 |
| `observability/evals.py` | Vidhi/Naman | Shashank runs | Ph3–4 |

**Nothing is edited by two people.** Read-only access is OK; write-only ownership.

---

## Phase synchronisation

| Phase | Shashank | Priyal | Vidhi/Naman | Blocker? |
|---|---|---|---|---|
| **0** | SQLite schema, Chroma, embedder | — | Prompts, LLM tiers | Shashank → rest; Vidhi/Naman → Shashank |
| **1** | Chunker, anonymizer, multimodal | Session/message CRUD | Triage nodes 1–7 (normalize–route) | — |
| **2** | Retrieval (vector + hybrid) | Memory manager, context | Tools, Jira adapter | Shashank retrieval → Vidhi/Naman tools |
| **3** | ACL, seed corpus, eval A/B | Summary inference, follow-ups | Guardrails, reflect node | Shashank corpus → Vidhi/Naman eval |
| **4** | Index validation, consistency check | Handle_message entry point | API wiring, integration tests | Priyal → Vidhi/Naman route wiring |

**Critical path:** Shashank Ph0 → Ph1 → Vidhi/Naman Ph1 (retrieval depends on chunker).
Priyal Ph1 can start in parallel (session/message don't depend on Shashank).

---

## Interface contracts (frozen once published)

### Shashank → Vidhi/Naman: `retrieve()`

```python
from rag.rag_retriever import retrieve
from rag.schemas import RetrievedChunk

def retrieve(
    query: str,
    user: dict,  # {"id": "...", "role": "...", "clearances": [...]}
    summary: str = "",
    filters: dict[str, str] = {},
    decompose: bool = False,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """
    - Returns top-k chunks, ACL-filtered, never unauthorized content
    - Scores: vector_rank, keyword_rank, rerank_score
    - Metadata includes doc_type, team, category, sensitivity
    - Decompose=True means "this is a retry with split queries"
    """
```

**Never changes.** Type signature is the contract. If you need more output, ask Shashank to
add fields to `RetrievedChunk`, not to return a different shape.

### Priyal → Vidhi/Naman: `handle_message()`

```python
from chatbot.conversation_manager import handle_message
from rag.schemas import ChatRequest, ChatResponse

async def handle_message(
    request: ChatRequest,  # {"message": "...", "session_id": "...", "filters": {...}}
    user: dict,
) -> ChatResponse:
    """
    - Creates/resumes session per session_id or user.id (single if pinned)
    - Retrieves from KB via Shashank's retrieve()
    - Returns answer with citations + suggestions
    - Updates rolling summary every 6 turns
    """
```

**Frozen.** Priyal owns the signature; Vidhi/Naman call it exactly as typed.

### Vidhi/Naman → Priyal: `run_turn()` (internal)

```python
def run_turn(
    question: str,
    user: dict,
    summary: str = "",
    history: list | None = None,
    filters: dict | None = None,
    trace=None,
) -> dict:
    """
    Triage graph execution. Priyal does NOT call this.
    Only Vidhi/Naman use it internally in agents.py.
    """
```

---

## Merge conflict prevention

**Rule 1: One editor per file.** You will see conflicts only if two people edit the same
file in the same phase. Since ownership is non-overlapping, this should not happen.

**Rule 2: Config changes are coordinated.** If you add a new env var or setting:
1. Add it to `config.py` in your phase
2. Document it in the phase task: "done when: `settings.NEW_SETTING` is readable"
3. Notify the other teams in the Jira comment

**Example:** Vidhi/Naman add `REASONING_MODEL` in Ph0. Shashank doesn't touch it. Later,
Vidhi/Naman add `VISION_MODEL` in Ph0. Still no conflict.

**Rule 3: Imports are read-only after published.** Once Shashank publishes
`rag/rag_retriever.py` in Ph1, Vidhi/Naman imports it; Shashank never changes the
function signature. Additions (e.g., `optional_param: int | None = None`) are safe; changes
to required params will break Vidhi/Naman's code.

**Rule 4: SQLite schema is frozen in Ph0.** Once Shashank publishes `models.py`, no
migrations. If a new field is needed mid-build, it is added to a new table or as a JSON
column (does not require schema migration).

---

## Integration test schedule

| Phase | Integration to test | Who runs it | Blockers |
|---|---|---|---|
| **Ph1 end** | Shashank's chunker on real tickets | Vidhi/Naman | Seed corpus exists |
| **Ph2 end** | Retrieve from live Chroma in Priyal test | Priyal | Chunker + embedder shipped |
| **Ph2 end** | Retrieve from live Chroma in Vidhi/Naman test | Vidhi/Naman | Chunker + embedder shipped |
| **Ph3 end** | E2E: normalize → retrieve → classify (no sync yet) | Vidhi/Naman | All retrieval online |
| **Ph3 end** | Multi-session chat: Priyal + Shashank | Priyal | Retrieval online |
| **Ph4 end** | E2E: ticket in → triage → Jira | Vidhi/Naman | All three layers online |
| **Ph4 end** | Cold-start demo: reset DB, re-index, triage one ticket | All three | All shipped |

---

## Jira board setup

Create an epic: **[SCRUM-0] TicketSphere Backend**

Under it, create three feature stories:

- **[SCRUM-xxx] RAG & Data Layer** (Shashank's parent story)
  - [SCRUM-xxx-1] Phase 0: Schema & Setup
  - [SCRUM-xxx-2] Phase 1: Ingest & Anonymisation
  - [SCRUM-xxx-3] Phase 2: Hybrid Retrieval
  - [SCRUM-xxx-4] Phase 3: ACL & Validation
  - [SCRUM-xxx-5] Phase 4: Integration & Eval

- **[SCRUM-xxx] Chatbot & Memory** (Priyal's parent story)
  - [SCRUM-xxx-1] Phase 1: Session Management
  - [SCRUM-xxx-2] Phase 2: Memory & Summarisation
  - [SCRUM-xxx-3] Phase 3: Context Assembly
  - [SCRUM-xxx-4] Phase 4: Entry Point & Integration

- **[SCRUM-xxx] LLM, Agents & Jira** (Vidhi & Naman's parent story)
  - [SCRUM-xxx-1] Phase 0: Prompts & Setup
  - [SCRUM-xxx-2] Phase 1: Triage Graph
  - [SCRUM-xxx-3] Phase 2: Tools & Jira
  - [SCRUM-xxx-4] Phase 3: Guardrails
  - [SCRUM-xxx-5] Phase 4: API & Integration

Link dependencies: RAG Ph0 blocks all Ph1s; Shashank Ph2 blocks Vidhi Ph1 (retrieve).

---

## Communication protocol

**Slack channel:** #brainbytes-backend (or your team Slack)

**Daily stand-up points:**
- What shipped yesterday (from the phase "done when" list)
- What blocks today (dependencies on other teams)
- No surprises in the API signature or data model

**Before each phase transition** (e.g., Shashank done Ph1, moving to Ph2):
- Post a summary in Slack: "Phase 1 shipped; retrieve() is live and tested with 10 tickets"
- Ping anyone who depends on it: "Vidhi/Naman, your phase 2 tools.py can now call retrieve()"

**If a signature needs to change:**
- Shashank changes `retrieve()` → posts in Slack immediately + links the PR
- Vidhi/Naman updates their code to match, same day
- Priyal is unaffected (she doesn't call retrieve directly)

**Jira board updates** happen once per day (at standup).

---

## Success criteria

**At the end of 20 hours:**

- [ ] Shashank: 500-ticket corpus indexed, A/B eval complete, retrieve() works with Vidhi/Naman's tooling
- [ ] Priyal: handle_message() called from `/chat` and `/chatbot`, multi-session isolation proven
- [ ] Vidhi/Naman: run_turn() completes all 10 nodes, a ticket syncs to Jira, guardrails block injections
- [ ] All three: zero merge conflicts on git (every file has one owner)
- [ ] Frontend (Trapti): can call all three endpoints; flows work end-to-end

**Measure of success:** the demo script in BLUEPRINT.md §13 runs without error.
