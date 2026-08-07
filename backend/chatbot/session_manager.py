"""Session lifecycle — create, resolve, list, rename, delete.

A session is the unit of ownership: every message, every audit entry and every memory
read is scoped by session_id, and a session belongs to exactly one user. All lookups
go through `get_session`, which enforces that ownership.
"""

from __future__ import annotations

from db.sqlite.models import ChatMessage, ChatSession, SessionLocal
from guardrails.governance import audit

# First user message becomes the title, truncated to this.
TITLE_CHARS = 60

# The chatbot widget is deliberately single-session: one continuous thread per user,
# always resumed, never listed. Named so it is recognisable in the sessions table.
CHATBOT_TITLE = "Knowledge Base Assistant"


def create_session(user_id: str, title: str = "New conversation") -> ChatSession:
    with SessionLocal() as s:
        session = ChatSession(user_id=user_id, title=title[:TITLE_CHARS])
        s.add(session)
        s.commit()
        s.refresh(session)
        audit.record("session.created", user_id=user_id, resource=session.id)
        return session


def get_session(session_id: str, user_id: str) -> ChatSession | None:
    """Returns None if the session does not exist *or* belongs to someone else —
    the caller cannot tell the difference, which is the point."""
    with SessionLocal() as s:
        return s.query(ChatSession).filter_by(id=session_id, user_id=user_id).first()


def resolve_session(session_id: str | None, user_id: str, first_message: str = "") -> ChatSession:
    """Get the named session or start a fresh one titled from the first message."""
    if session_id:
        existing = get_session(session_id, user_id)
        if existing:
            return existing
    return create_session(user_id, title=first_message.strip() or "New conversation")


def pinned_session(user_id: str) -> ChatSession:
    """The one session the chatbot endpoint always uses.

    Everything the widget asks lands in a single thread, so its memory and rolling
    summary accumulate across the whole demo instead of resetting per question.
    Calling twice returns the same session id.
    """
    with SessionLocal() as s:
        existing = (
            s.query(ChatSession).filter_by(user_id=user_id, title=CHATBOT_TITLE).first()
        )
        if existing:
            return existing
    return create_session(user_id, title=CHATBOT_TITLE)


def reset_pinned_session(user_id: str) -> str:
    """Clear the chatbot thread without deleting the session it is pinned to."""
    session = pinned_session(user_id)
    clear_messages(session.id)
    with SessionLocal() as s:
        row = s.get(ChatSession, session.id)
        if row:
            row.summary = ""
            s.commit()
    audit.record("chatbot.reset", user_id=user_id, resource=session.id)
    return session.id


def write_message(session_id: str, role: str, content: str, **fields) -> ChatMessage:
    """Persist one chat message on a session."""
    with SessionLocal() as s:
        message = ChatMessage(session_id=session_id, role=role, content=content, **fields)
        s.add(message)
        s.commit()
        s.refresh(message)
        return message


def list_messages(
    session_id: str,
    page: int = 1,
    page_size: int = 5,
) -> tuple[list[ChatMessage], int]:
    """Paginated messages for a session, oldest first within the page window.

    Returns (rows, total). Page is 1-indexed.
    """
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    with SessionLocal() as s:
        q = s.query(ChatMessage).filter_by(session_id=session_id)
        total = q.count()
        rows = (
            q.order_by(ChatMessage.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return list(rows), total


def clear_messages(session_id: str) -> int:
    """Delete every message in a session. Returns how many rows were removed."""
    with SessionLocal() as s:
        deleted = s.query(ChatMessage).filter_by(session_id=session_id).delete()
        s.commit()
        return deleted


def touch(session_id: str, title: str | None = None) -> None:
    """Bump updated_at; optionally set title on a still-untitled multi-session thread.

    The pinned chatbot drawer keeps CHATBOT_TITLE forever.
    """
    with SessionLocal() as s:
        session = s.get(ChatSession, session_id)
        if not session:
            return
        if title and session.title == "New conversation":
            session.title = title[:TITLE_CHARS]
        s.commit()


def set_title(session_id: str, title: str) -> None:
    """Set a session title after first-turn inference (never renames the pinned drawer)."""
    with SessionLocal() as s:
        session = s.get(ChatSession, session_id)
        if not session or session.title == CHATBOT_TITLE:
            return
        if session.title == "New conversation" or not session.title:
            session.title = title[:TITLE_CHARS]
            s.commit()


def delete_session(session_id: str, user_id: str) -> bool:
    with SessionLocal() as s:
        session = s.query(ChatSession).filter_by(id=session_id, user_id=user_id).first()
        if not session:
            return False
        s.query(ChatMessage).filter_by(session_id=session_id).delete()
        s.delete(session)
        s.commit()
    audit.record("session.deleted", user_id=user_id, resource=session_id)
    return True
