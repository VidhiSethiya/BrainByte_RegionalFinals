# TicketSphere — Chatbot & Conversation Management

**Owner:** Priyal · **Window:** ~6 of the 24 hours

This plan owns the conversation layer: memory, session management, context assembly, and
the entry point that Vidhi/Naman's agents call to answer questions. You build what the
knowledge-base Q&A surface uses — both the `/chat` multi-session endpoint and the `/chatbot`
single-session drawer.

---

## Contract signatures

Vidhi/Naman call this from `api.py`:

```python
# backend/chatbot/conversation_manager.py
from rag.schemas import ChatResponse

async def handle_message(
    request: ChatRequest,           # {"message": "...", "session_id": "...", "filters": {...}}
    user: dict,                     # {"id", "username", "role", "clearances"}
) -> ChatResponse:
    """
    End-to-end chat pipeline:
    1. Load/create session
    2. Assemble context: summary + last 6 messages + retrieved chunks
    3. Call agent (Vidhi/Naman's run_turn)
    4. Update session summary
    5. Return response with citations
    """
```

You call Shashank's retriever:

```python
# Call signature you depend on
from rag.rag_retriever import retrieve

chunks = retrieve(
    query=rewritten_query,
    user=user,
    summary=session.summary,
    filters=request.filters or {},
)
```

You depend on SQLite models from Shashank:

```python
from db.sqlite.models import ChatSession, ChatMessage, SessionLocal
```

---

## Phases

### Phase 1 — Core session management (0–2h)

| # | Task | Files | Done when |
|---|---|---|---|
| 1.1 | Session model & factory: create/retrieve/delete chatbot pinned session per user | `backend/chatbot/session_manager.py` | `session_manager.pinned_session(user_id)` returns the same session ID on second call |
| 1.2 | Write/read/clear chat messages; query by session with pagination | `backend/chatbot/session_manager.py`, SQLAlchemy queries | Test: write 10 messages, retrieve page 1 (5 msgs), page 2 (5 msgs), clear all |
| 1.3 | Test `/sessions` and `/sessions/{id}/messages` endpoints exist (Vidhi/Naman wire them) | Integration test file | `curl /sessions` returns 200 + paginated list |

### Phase 2 — Memory & summarisation (2–4h)

| # | Task | Files | Done when |
|---|---|---|---|
| 2.1 | Rolling conversation summary: on every 6th turn, summarise the last 6 + existing summary, store | `backend/chatbot/memory_manager.py` | 10-turn conversation; summary at turn 6 and turn 12 captures key facts, <120 words |
| 2.2 | Short-term buffer: replay last 6 messages verbatim | `backend/chatbot/memory_manager.py::get_history()` | History includes both user and assistant messages in order |
| 2.3 | Query rewrite using summary (so follow-ups become standalone); call Shashank's retriever | `backend/chatbot/memory_manager.py::rewrite_query()` | "What about the second one?" + summary → "Tell me about the second AWS outage" |

### Phase 3 — Context assembly (4–5h)

| # | Task | Files | Done when |
|---|---|---|---|
| 3.1 | Build conversation context: system persona + retrieved chunks + session summary + history | `backend/chatbot/context_manager.py` | Assembled prompt is under the token budget and retrieves on every turn |
| 3.2 | Follow-up suggestion: after each answer, propose 3 next questions from the KB | `backend/chatbot/context_manager.py::suggest_followups()` | Suggestions are answerable from indexed docs, not generic |
| 3.3 | Conversation title inference: auto-title sessions after first turn | `backend/chatbot/context_manager.py` | Multi-turn test: first exchange, title is one-line summary of the topic |

### Phase 4 — Entry point & integration (5–6h)

| # | Task | Files | Done when |
|---|---|---|---|
| 4.1 | `handle_message()` orchestrator: load session → rewrite → retrieve → call agent (Vidhi/Naman) → update summary → return | `backend/chatbot/conversation_manager.py` | Test: single-turn and multi-turn calls both return `ChatResponse` with citations |
| 4.2 | Pinned session per user for `/chatbot` drawer; ignore client's `session_id` | `backend/chatbot/conversation_manager.py` | Drawer test: two users chat independently; summaries don't bleed |
| 4.3 | Multi-session `/chat` assistant; caller supplies session_id or new one is created | `backend/chatbot/conversation_manager.py` | Create session A, chat, switch to session B, chat, back to A — history is isolated |

**Total estimated: 6h of 20.**

---

## File ownership

**You own:**
- `backend/chatbot/*.py` (all conversation logic)
- `backend/chatbot/__init__.py`

**You do NOT touch:**
- `backend/api.py` (Vidhi/Naman wire the endpoints)
- `backend/rag/*` (Shashank owns this)
- `backend/ai/*` (Vidhi/Naman own this)
- `db/sqlite/models.py` (Shashank owns, you import from)

**Shared:**
- `backend/ai/prompts.py` — you do NOT edit this; Vidhi/Naman define all prompts there

---

## Interface stability

To avoid merge conflicts with Vidhi/Naman:

1. **Don't call `run_turn()` directly.** Define a stub in `api.py` that Vidhi/Naman fills:

```python
# api.py (you do not write this, but you need to know the signature)
from ai.agents import run_turn

async def chat():
    """
    Vidhi/Naman write this. You just call handle_message() from it.
    """
```

2. **Your `handle_message()` signature is frozen** — Vidhi/Naman depend on it.

3. **Return `ChatResponse` exactly** (from `rag.schemas`), never a modified version.

4. **Never import `api.py`** — it imports you, not the reverse.

---

## Known risks

| Risk | Mitigation |
|---|---|
| Token budget is exhausted, summary doesn't fit | Compress the summary; test with a mock 2K-token budget |
| Follow-up suggestions are repetitive or out of domain | Evaluate against the KB; if half the suggestions fail to ground, the prompt needs tuning (Vidhi/Naman's job) |
| Summary updates collide with simultaneous retrievals | Use a session-level write lock; `SessionLocal()` already has transaction isolation |
| Memory leaks: old sessions never cleaned up | Add a `created_at` to ChatSession; purge sessions > 30 days old on boot (separate task, not in this plan) |

---

## Jira integration

Create these stories:

- **[SCRUM-xxx] Chatbot - Phase 1: Session Management**
- **[SCRUM-xxx] Chatbot - Phase 2: Memory & Summarisation**
- **[SCRUM-xxx] Chatbot - Phase 3: Context Assembly**
- **[SCRUM-xxx] Chatbot - Phase 4: Integration**

---

## Definition of done

- [ ] All `handle_message()` tests pass; single-turn, multi-turn, multi-session
- [ ] Summaries are compressed, on-time, and capture key facts
- [ ] Follow-up suggestions are grounded in the KB (run them as test queries)
- [ ] No unprompted model calls — every LLM invocation is explicit and traced
- [ ] Session isolation is verified: two users' conversations never cross
- [ ] Message pagination works and is tested at 5, 10, 50 messages
