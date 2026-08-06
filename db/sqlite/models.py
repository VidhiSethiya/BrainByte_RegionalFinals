"""SQLAlchemy models + session factory.

Relational store holds identity, conversation history, audit trail and feedback.
Document *content* lives in Chroma; only its governance metadata is mirrored here so
the admin UI can list/filter documents without touching the vector store.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

from config import settings


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> dt.datetime:
    # Naive UTC on purpose. SQLite returns naive datetimes, so a tz-aware value would
    # round-trip differently than it was written — which would break the audit log's
    # hash chain, since the timestamp is part of what each entry hashes.
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="viewer")
    # Clearance tags matched against a document's `allowed_roles`/`tags` metadata at
    # query time. [PLACEHOLDER: DOMAIN_CLEARANCE_TAGS]
    clearances = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=_now)

    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def verify_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "clearances": self.clearances or [],
        }


class Document(Base):
    """Governance mirror of what is indexed in Chroma."""

    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_uuid)
    filename = Column(String, nullable=False)
    modality = Column(String, nullable=False, default="text")  # text | pdf | image
    source = Column(String, nullable=True)
    # Access control enforced inside the retriever, not in the route.
    allowed_roles = Column(JSON, nullable=False, default=list)
    sensitivity = Column(String, nullable=False, default="internal")
    chunk_count = Column(Integer, default=0)
    status = Column(String, default="indexed")  # indexed | failed | pending
    # [PLACEHOLDER: DOMAIN_DOCUMENT_ATTRIBUTES] e.g. department, contract_id, patient_id
    attributes = Column(JSON, nullable=False, default=dict)
    uploaded_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "modality": self.modality,
            "source": self.source,
            "allowed_roles": self.allowed_roles or [],
            "sensitivity": self.sensitivity,
            "chunk_count": self.chunk_count,
            "status": self.status,
            "attributes": self.attributes or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String, default="New conversation")
    # Rolling summary maintained by chatbot/memory_manager.py
    summary = Column(Text, default="")
    created_at = Column(DateTime, default=_now, index=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    citations = Column(JSON, default=list)
    # Per-turn telemetry so the analytics tab needs no separate store.
    latency_ms = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    groundedness = Column(Float, nullable=True)
    blocked_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "citations": self.citations or [],
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "groundedness": self.groundedness,
            "blocked_reason": self.blocked_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(Base):
    """Append-only, hash-chained. Never UPDATE or DELETE a row here."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=True, index=True)
    action = Column(String, nullable=False, index=True)
    resource = Column(String, nullable=True)
    details = Column(JSON, default=dict)
    prev_hash = Column(String, nullable=True)
    entry_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=_now, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "action": self.action,
            "resource": self.resource,
            "details": self.details or {},
            "entry_hash": self.entry_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Feedback(Base):
    """Thumbs + optional human-in-the-loop correction."""

    __tablename__ = "feedback"

    id = Column(String, primary_key=True, default=_uuid)
    message_id = Column(String, ForeignKey("chat_messages.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1 = up, -1 = down
    comment = Column(Text, default="")
    corrected_answer = Column(Text, nullable=True)
    reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "rating": self.rating,
            "comment": self.comment,
            "corrected_answer": self.corrected_answer,
            "reviewed": self.reviewed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvalResult(Base):
    """One row per evaluated query — powers the Evals dashboard tab."""

    __tablename__ = "eval_results"

    id = Column(String, primary_key=True, default=_uuid)
    question = Column(Text, nullable=False)
    answer = Column(Text, default="")
    groundedness = Column(Float, default=0.0)
    context_precision = Column(Float, default=0.0)
    context_recall = Column(Float, default=0.0)
    hallucination = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "groundedness": round(self.groundedness or 0, 3),
            "context_precision": round(self.context_precision or 0, 3),
            "context_recall": round(self.context_recall or 0, 3),
            "hallucination": round(self.hallucination or 0, 3),
            "latency_ms": self.latency_ms,
            "total_tokens": self.total_tokens,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


engine = create_engine(settings.DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables and a demo admin. Safe to call on every boot."""
    settings.ensure_dirs()
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        if not s.query(User).filter_by(username="admin").first():
            admin = User(username="admin", role="admin", clearances=["all"])
            admin.set_password("admin123")  # demo credentials — change before a real deploy
            s.add(admin)
            s.commit()
