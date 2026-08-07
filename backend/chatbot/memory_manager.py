"""Two-tier conversation memory.

  Short-term: the last N turns, verbatim. Cheap, exact, what the model needs to
              resolve "it" and "that one".
  Long-term:  a rolling LLM summary, refreshed every SUMMARY_EVERY turns. Keeps
              entities and decisions from a 40-turn conversation inside a small
              context window without replaying the whole transcript.

`rewrite_query` uses the summary to make follow-ups searchable before they hit
Shashank's retriever.
"""

from __future__ import annotations

from ai.llm import chat, chat_json
from ai.prompts import QUERY_REWRITE_PROMPT, SUMMARIZE_CONVERSATION_PROMPT
from db.sqlite.models import ChatMessage, ChatSession, SessionLocal
from observability.telemetry import log

RECENT_TURNS = 6          # messages (not exchanges) replayed verbatim
SUMMARY_EVERY = 6         # refresh the rolling summary every N messages
MAX_MESSAGE_CHARS = 1500  # truncate long pasted content in the replay window
MAX_SUMMARY_WORDS = 120


def recent_messages(session_id: str, limit: int = RECENT_TURNS) -> list[ChatMessage]:
    with SessionLocal() as s:
        rows = (
            s.query(ChatMessage)
            .filter_by(session_id=session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
    return list(reversed(rows))


def get_history(session_id: str, limit: int = RECENT_TURNS) -> list[ChatMessage]:
    """Short-term buffer: last N messages in chronological order (user + assistant)."""
    return recent_messages(session_id, limit=limit)


def get_summary(session_id: str) -> str:
    with SessionLocal() as s:
        session = s.get(ChatSession, session_id)
        return (session.summary or "") if session else ""


def append_message(session_id: str, role: str, content: str, **fields) -> ChatMessage:
    with SessionLocal() as s:
        message = ChatMessage(session_id=session_id, role=role, content=content, **fields)
        s.add(message)
        s.commit()
        s.refresh(message)
        return message


def rewrite_query(question: str, summary: str = "", trace=None) -> str:
    """Turn a follow-up into a standalone search query using the rolling summary.

    Example: "What about the second one?" + summary about AWS outages
           → "Tell me about the second AWS outage"
    """
    if not (summary or "").strip():
        return question
    try:
        result = chat_json(
            QUERY_REWRITE_PROMPT.format(summary=summary, question=question),
            fast=True,
            trace=trace,
            default={},
        )
        rewritten = ((result or {}).get("query") or "").strip()
        return rewritten or question
    except Exception as exc:  # noqa: BLE001 - raw question beats a failed rewrite
        log.warning("query rewrite failed: %s", exc)
        return question


def maybe_summarize(session_id: str, trace=None) -> str:
    """Refresh the rolling summary if enough new turns have accumulated."""
    with SessionLocal() as s:
        total = s.query(ChatMessage).filter_by(session_id=session_id).count()
        session = s.get(ChatSession, session_id)
        if not session:
            return ""
        current = session.summary or ""

    if total == 0 or total % SUMMARY_EVERY != 0:
        return current

    turns = "\n".join(
        f"{m.role}: {m.content[:MAX_MESSAGE_CHARS]}"
        for m in recent_messages(session_id, SUMMARY_EVERY)
    )
    try:
        updated = chat(
            SUMMARIZE_CONVERSATION_PROMPT.format(summary=current or "(none)", turns=turns),
            fast=True,
            temperature=0,
            trace=trace,
        )
    except Exception as exc:  # noqa: BLE001 - a stale summary beats a failed turn
        log.warning("summary refresh failed: %s", exc)
        return current

    if updated:
        # Soft-enforce the <120 word budget from the plan.
        words = updated.split()
        if len(words) > MAX_SUMMARY_WORDS:
            updated = " ".join(words[:MAX_SUMMARY_WORDS])
        with SessionLocal() as s:
            session = s.get(ChatSession, session_id)
            if session:
                session.summary = updated
                s.commit()
        return updated
    return current
