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
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

from config import settings
from observability.telemetry import log
from rag.schemas import normalize_severity


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
    # Clearance tags matched against chunk `acl_<tag>` metadata at query time.
    # Team membership rides here: engineer clearances are one of ops|azure|aws|gcp;
    # manager/admin use ["all"].
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
    # TicketSphere Chroma attrs mirrored for the KB table: doc_type, team, service,
    # environment, category, severity, resolved, resolution_minutes.
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


class Ticket(Base):
    """Operational ticket record — gold labels stay here, never in chunk text."""

    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_ticket_source_ext"),)

    id = Column(String, primary_key=True, default=_uuid)
    external_id = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, default="synthetic")  # jira | synthetic | manual
    title = Column(String, nullable=False, default="")
    body_masked = Column(Text, nullable=False, default="")
    application = Column(String, default="")
    environment = Column(String, default="prod")  # prod | uat | dev
    channel = Column(String, default="")
    # Source-system identity, not TicketSphere identity — a Jira email/display
    # name or a synthetic placeholder, never one of our own User rows. Additive
    # column per .claude/plans/INTEGRATION.md's no-migration rule; see
    # integrations/jira.py::_to_ticket_dict for where these are populated.
    reporter = Column(String, default="")
    assignee = Column(String, default="")
    category = Column(String, default="")
    subcategory = Column(String, default="")
    severity = Column(String, default="")  # Jira Priority names: Highest|High|Medium|Low
    priority_score = Column(Integer, default=0)
    assigned_team = Column(String, default="")  # ops | azure | aws | gcp
    status = Column(String, default="new", index=True)
    # new → triaged → awaiting_approval → routed → synced | failed
    confidence = Column(Float, default=0.0)
    needs_human = Column(Boolean, default=False)
    overridden_by = Column(String, ForeignKey("users.id"), nullable=True)
    override_reason = Column(Text, default="")
    # Gold labels for held-out accuracy — stripped from indexed text.
    true_category = Column(String, nullable=True)
    true_severity = Column(String, nullable=True)
    true_team = Column(String, nullable=True)
    held_out = Column(Boolean, default=False, index=True)
    sync_attempts = Column(Integer, default=0)
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=_now, index=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    def to_dict(self) -> dict:
        from rag.schemas import normalize_severity

        return {
            "id": self.id,
            "external_id": self.external_id,
            "source": self.source,
            "title": self.title,
            "body_masked": self.body_masked,
            "application": self.application,
            "environment": self.environment,
            "channel": self.channel,
            "reporter": self.reporter,
            "assignee": self.assignee,
            "category": self.category,
            "subcategory": self.subcategory,
            "severity": normalize_severity(self.severity) if self.severity else "",
            "priority_score": self.priority_score,
            "assigned_team": self.assigned_team,
            "status": self.status,
            "confidence": self.confidence,
            "needs_human": self.needs_human,
            "overridden_by": self.overridden_by,
            "override_reason": self.override_reason,
            "true_category": self.true_category,
            "true_severity": normalize_severity(self.true_severity) if self.true_severity else self.true_severity,
            "true_team": self.true_team,
            "held_out": self.held_out,
            "sync_attempts": self.sync_attempts,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TriageRun(Base):
    """One agent execution per ticket — model, cost, full TriageDecision JSON."""

    __tablename__ = "triage_runs"

    id = Column(String, primary_key=True, default=_uuid)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False, index=True)
    decision_json = Column(JSON, nullable=False, default=dict)
    model = Column(String, default="")
    tier = Column(String, default="standard")  # fast | standard | deep
    tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    trace_id = Column(String, default="", index=True)
    guardrails_fired = Column(JSON, default=list)
    created_at = Column(DateTime, default=_now, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticket_id": self.ticket_id,
            "decision_json": self.decision_json or {},
            "model": self.model,
            "tier": self.tier,
            "tokens": self.tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "trace_id": self.trace_id,
            "guardrails_fired": self.guardrails_fired or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SyncState(Base):
    """Poller watermark, one row per ticket source. Keyed on `source` (e.g.
    "jira") rather than a single fixed row, so a future second source doesn't
    collide with the first.

    Exists because integrations/poller.py used to hold this only as an
    in-memory module global — correct within one running process, but every
    restart lost it and the poller re-fetched (and re-triaged, full LLM cost)
    every ticket on the board from the beginning. One row, updated on every
    successful poll, is all persistence this needs.
    """

    __tablename__ = "sync_state"

    source = Column(String, primary_key=True)
    watermark = Column(String, nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


engine = create_engine(
    settings.DATABASE_URL,
    future=True,
    # integrations/poller.py now triages a sync batch's tickets concurrently
    # (ai.llm.parallel_map, bounded by MAX_PARALLEL_WORKERS) — several threads
    # can commit around the same moment. SQLite's default rollback-journal mode
    # only ever allows one writer at a time and gives up after the sqlite3
    # driver's default 5s busy-wait, which is tight enough to occasionally
    # surface as "database is locked" under that load. WAL lets readers and the
    # one active writer coexist, and the longer timeout below is the cheap
    # remaining insurance for the rare moment two commits still line up.
    connect_args={"timeout": 30} if settings.DATABASE_URL.startswith("sqlite") else {},
)
if settings.DATABASE_URL.startswith("sqlite"):
    with engine.connect() as _conn:
        _conn.exec_driver_sql("PRAGMA journal_mode=WAL")
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


_DEMO_USERS = [
    ("admin", "admin123", "admin", ["all"]),
    ("manager", "manager123", "admin", ["all"]),
    ("ops1", "ops123", "engineer", ["ops"]),
    ("azure1", "azure123", "engineer", ["azure"]),
    ("aws1", "aws123", "engineer", ["aws"]),
    ("gcp1", "gcp123", "engineer", ["gcp"]),
]


def _migrate_sqlite_columns() -> None:
    """Additive column sync for tables that already exist.

    create_all() does not ALTER existing tables. TicketSphere added reporter/
    assignee (and may add more) after early demos created tickets without them —
    without this, every Jira poll dies with OperationalError: no such column.
    """
    needed = {
        "tickets": {
            "reporter": "VARCHAR DEFAULT ''",
            "assignee": "VARCHAR DEFAULT ''",
        },
    }
    with engine.begin() as conn:
        for table, cols in needed.items():
            existing = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            }
            if not existing:
                continue  # table not created yet; create_all handles it
            for name, ddl in cols.items():
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    _migrate_severity_to_priority()


def _migrate_severity_to_priority() -> None:
    """Rewrite retired band values to the canonical Jira Priority names.

    `tickets.severity` holds Highest/High/Medium/Low — the same vocabulary Jira,
    the API and the console all speak. Two earlier vocabularies exist in rows
    written before that settled: the original S1–S4 severity scale, and a
    short-lived P1–P4 band. Neither matches on comparison any more, so the queue
    filter, the analytics grouping, the auto-approve band and the Jira write-back
    would all silently stop working on those rows rather than fail loudly.

    Idempotent: after the first pass there is nothing left to update.
    """
    mapping = {
        "S1": "Highest", "S2": "High", "S3": "Medium", "S4": "Low",
        "P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low",
    }
    columns = ("severity", "true_severity")
    with engine.begin() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(tickets)").fetchall()}
        if not existing:
            return
        moved = 0
        for column in columns:
            if column not in existing:
                continue
            for old_value, new_value in mapping.items():
                result = conn.exec_driver_sql(
                    f"UPDATE tickets SET {column} = ? WHERE {column} = ?", (new_value, old_value)
                )
                moved += result.rowcount or 0
    if moved:
        log.info("migrated %d ticket row(s) to Jira Priority names", moved)


def init_db() -> None:
    """Create tables and TicketSphere demo users. Safe to call on every boot."""
    settings.ensure_dirs()
    Base.metadata.create_all(engine)
    _migrate_sqlite_columns()
    with SessionLocal() as s:
        for username, password, role, clearances in _DEMO_USERS:
            if s.query(User).filter_by(username=username).first():
                continue
            user = User(username=username, role=role, clearances=list(clearances))
            user.set_password(password)
            s.add(user)
        s.commit()
