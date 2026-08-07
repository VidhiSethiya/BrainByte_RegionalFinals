"""Two-tier conversation memory.

  Short-term: the last N turns, verbatim — resolves "it", "that one", and
              "what did I ask last".
  Long-term:  a rolling LLM summary, refreshed every SUMMARY_EVERY turns.

`rewrite_query` uses summary + recent history so follow-ups stay searchable.
"""

from __future__ import annotations

from ai.llm import chat, chat_json
from ai.prompts import QUERY_REWRITE_PROMPT, SUMMARIZE_CONVERSATION_PROMPT
from db.sqlite.models import ChatMessage, ChatSession, SessionLocal
from observability.telemetry import log

RECENT_TURNS = 12         # richer two-way memory window
SUMMARY_EVERY = 6
MAX_MESSAGE_CHARS = 1500
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


def format_history(history: list[ChatMessage], max_chars: int = MAX_MESSAGE_CHARS) -> str:
    """Plain-text transcript for rewrite / conversational prompts."""
    lines: list[str] = []
    for m in history or []:
        role = m.role or "user"
        content = (m.content or "")[:max_chars]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def append_message(session_id: str, role: str, content: str, **fields) -> ChatMessage:
    with SessionLocal() as s:
        message = ChatMessage(session_id=session_id, role=role, content=content, **fields)
        s.add(message)
        s.commit()
        s.refresh(message)
        return message


def rewrite_query(
    question: str,
    summary: str = "",
    history: list[ChatMessage] | None = None,
    trace=None,
) -> str:
    """Turn a follow-up into a standalone search query using summary + recent turns."""
    hist_text = format_history(history or [])
    memory_blob = summary.strip()
    if hist_text:
        memory_blob = (
            f"{memory_blob}\n\nRECENT TURNS:\n{hist_text}".strip()
            if memory_blob
            else f"RECENT TURNS:\n{hist_text}"
        )
    if not memory_blob:
        return question
    try:
        result = chat_json(
            QUERY_REWRITE_PROMPT.format(summary=memory_blob, question=question),
            fast=True,
            trace=trace,
            default={},
        )
        rewritten = ((result or {}).get("query") or "").strip()
        return rewritten or question
    except Exception as exc:  # noqa: BLE001
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
    except Exception as exc:  # noqa: BLE001
        log.warning("summary refresh failed: %s", exc)
        return current

    if updated:
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
