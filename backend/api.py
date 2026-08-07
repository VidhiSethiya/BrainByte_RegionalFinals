"""All HTTP routes, plus the request/response plumbing they share.

Sections:
  1. response envelope       ok() / fail()
  2. list-endpoint contract  pagination, sorting, filtering, searching
  3. rate limiting
  4. auth (JWT)
  5. routes

Business logic lives in the layer modules; a handler here should read as glue.

Response contract:
    success -> {"data": ..., "meta": {...}}
    failure -> {"error": {"code": ..., "message": ...}}
"""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any, Iterable, Type, TypeVar

import jwt
from flask import Blueprint, g, request
from pydantic import BaseModel, ValidationError
from sqlalchemy import asc, desc, or_
from werkzeug.utils import secure_filename

from ai import tools
from ai.agents import ingest_and_triage
from ai.tools import ToolDenied
from chatbot import session_manager as sessions
from chatbot.conversation_manager import handle_message
from config import settings
from db.sqlite.models import (
    AuditLog,
    ChatMessage,
    ChatSession,
    Document,
    EvalResult,
    Feedback,
    SessionLocal,
    Ticket,
    TriageRun,
    User,
)
from db.vectordb import vector_store
from guardrails.governance import audit
from integrations.poller import get_watermark, poll_once
from observability import evals
from observability.telemetry import log, recent_traces, usage_summary
from rag import rag_indexer
from rag.rag_retriever import retrieve
from rag.schemas import ChatRequest, FeedbackRequest, LoginRequest, OverrideRequest, TicketIngestRequest

api_bp = Blueprint("api", __name__)

T = TypeVar("T", bound=BaseModel)

ALLOWED_UPLOAD_SUFFIXES = {
    ".txt", ".md", ".log", ".csv", ".json", ".pdf", ".png", ".jpg", ".jpeg", ".webp",
}


# =============================================================================
# 1. Response envelope
# =============================================================================


def ok(data: Any, meta: dict | None = None, status: int = 200):
    return {"data": data, "meta": meta or {}}, status


def fail(code: str, message: str, status: int = 400):
    return {"error": {"code": code, "message": message}}, status


# =============================================================================
# 2. List-endpoint contract
#    ?page=1&page_size=20&sort=created_at&order=desc&q=text&filter[status]=indexed
# =============================================================================

MAX_PAGE_SIZE = 100
_FILTER_RE = re.compile(r"^filter\[(\w+)\]$")


@dataclass
class QueryParams:
    page: int = 1
    page_size: int = 20
    sort: str | None = None
    order: str = "desc"
    q: str = ""
    filters: dict[str, str] = field(default_factory=dict)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def parse_query_params(default_sort: str = "created_at") -> QueryParams:
    args = request.args
    try:
        page = max(1, int(args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        page_size = min(MAX_PAGE_SIZE, max(1, int(args.get("page_size", 20))))
    except ValueError:
        page_size = 20

    filters = {}
    for key, value in args.items():
        m = _FILTER_RE.match(key)
        if m and value != "":
            filters[m.group(1)] = value

    return QueryParams(
        page=page,
        page_size=page_size,
        sort=args.get("sort") or default_sort,
        order="asc" if args.get("order", "desc").lower() == "asc" else "desc",
        q=(args.get("q") or "").strip(),
        filters=filters,
    )


def apply_query(query, model, params: QueryParams, searchable: Iterable[str] = ()):
    """Filter -> search -> sort. Unknown filter keys are ignored, not fatal."""
    for key, value in params.filters.items():
        col = getattr(model, key, None)
        if col is not None:
            query = query.filter(col == value)

    if params.q and searchable:
        needle = f"%{params.q}%"
        clauses = [getattr(model, c).ilike(needle) for c in searchable if hasattr(model, c)]
        if clauses:
            query = query.filter(or_(*clauses))

    sort_col = getattr(model, params.sort, None) if params.sort else None
    if sort_col is not None:
        query = query.order_by(desc(sort_col) if params.order == "desc" else asc(sort_col))
    return query


def paginate(query, params: QueryParams) -> tuple[list[Any], dict]:
    total = query.count()
    rows = query.limit(params.page_size).offset(params.offset).all()
    return rows, {
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "pages": (total + params.page_size - 1) // params.page_size,
    }


def validate_request(raw: object, model: Type[T]) -> tuple[T | None, str]:
    if not isinstance(raw, dict):
        return None, "request body must be a JSON object"
    try:
        return model.model_validate(raw), ""
    except ValidationError as exc:
        first = exc.errors()[0]
        field_name = ".".join(str(p) for p in first.get("loc", ())) or "body"
        return None, f"{field_name}: {first.get('msg', 'invalid')}"


# =============================================================================
# 3. Rate limiting — sliding window, in-process
# =============================================================================

_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_BUCKET_LOCK = threading.Lock()


def rate_limit(per_minute: int | None = None):
    limit = per_minute or settings.RATE_LIMIT_PER_MINUTE

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = getattr(g, "user", None)
            key = f"{fn.__name__}:{user['id'] if user else request.remote_addr}"
            now = time.time()
            with _BUCKET_LOCK:
                bucket = _BUCKETS[key]
                while bucket and now - bucket[0] > 60:
                    bucket.popleft()
                if len(bucket) >= limit:
                    retry_in = int(60 - (now - bucket[0])) + 1
                    return fail("rate_limited", f"Too many requests. Retry in {retry_in}s.", 429)
                bucket.append(now)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# =============================================================================
# 4. Auth
# =============================================================================


def _issue_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "clearances": user.clearances or [],
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=settings.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return fail("unauthorized", "Missing bearer token", 401)
        try:
            claims = jwt.decode(header[7:], settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return fail("token_expired", "Session expired, sign in again", 401)
        except jwt.InvalidTokenError:
            return fail("unauthorized", "Invalid token", 401)

        g.user = {
            "id": claims["sub"],
            "username": claims.get("username", ""),
            "role": claims.get("role", "viewer"),
            "clearances": claims.get("clearances", []),
        }
        return fn(*args, **kwargs)

    return wrapper


def require_role(*roles: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user["role"] not in roles:
                audit.record("access.denied", user_id=g.user["id"], resource=request.path)
                return fail("forbidden", "Insufficient permissions", 403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# =============================================================================
# 5. Routes
# =============================================================================

# --- health -----------------------------------------------------------------


@api_bp.get("/health")
def health():
    from ai.llm import resolve_provider

    return ok(
        {
            "status": "ok",
            "provider": resolve_provider()["name"],
            "chat_model": settings.LLM_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "retrieval_mode": settings.RETRIEVAL_MODE,
            "indexed_chunks": vector_store.count(),
            "domain": settings.DOMAIN,
        }
    )


# --- auth -------------------------------------------------------------------


@api_bp.post("/auth/login")
@rate_limit(per_minute=10)
def login():
    payload, error = validate_request(request.get_json(silent=True), LoginRequest)
    if error:
        return fail("validation_error", error, 422)

    with SessionLocal() as s:
        user = s.query(User).filter_by(username=payload.username).first()
        if not user or not user.verify_password(payload.password):
            audit.record("auth.failed", resource=payload.username)
            return fail("invalid_credentials", "Incorrect username or password", 401)
        audit.record("auth.login", user_id=user.id)
        return ok({"token": _issue_token(user), "user": user.to_dict()})


@api_bp.get("/auth/me")
@require_auth
def me():
    return ok(g.user)


# --- main AI pipeline -------------------------------------------------------


@api_bp.post("/chat")
@require_auth
@rate_limit()
def chat():
    """Full pipeline: guardrails -> retrieval -> agent -> guardrails -> audit.

    Multi-session: the caller supplies session_id, or a new session is created.
    """
    payload, error = validate_request(request.get_json(silent=True), ChatRequest)
    if error:
        return fail("validation_error", error, 422)
    response = handle_message(payload, g.user)
    return ok(response.model_dump(), {"trace_id": response.trace_id})


# --- chatbot (single session, knowledge-base Q&A) ---------------------------


@api_bp.post("/chatbot")
@require_auth
@rate_limit()
def chatbot():
    """The chat widget's endpoint. Deliberately single-session.

    Separate from /chat because the widget has different semantics: it always resumes
    one continuous thread per user rather than managing a session list, so its rolling
    summary and memory build up across the whole conversation. Any session_id the
    client sends is ignored — the server decides which thread this is.
    """
    body = request.get_json(silent=True) or {}
    body.pop("session_id", None)
    payload, error = validate_request(body, ChatRequest)
    if error:
        return fail("validation_error", error, 422)

    payload.session_id = sessions.pinned_session(g.user["id"]).id
    response = handle_message(payload, g.user)
    return ok(response.model_dump(), {"trace_id": response.trace_id})


@api_bp.get("/chatbot/history")
@require_auth
def chatbot_history():
    """Replay the single thread so the widget survives a page reload."""
    session = sessions.pinned_session(g.user["id"])
    with SessionLocal() as s:
        rows = (
            s.query(ChatMessage)
            .filter_by(session_id=session.id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )
    return ok([r.to_dict() for r in rows], {"session_id": session.id})


@api_bp.delete("/chatbot/history")
@require_auth
def chatbot_reset():
    return ok({"session_id": sessions.reset_pinned_session(g.user["id"])})


# --- sessions ---------------------------------------------------------------


@api_bp.get("/sessions")
@require_auth
def list_sessions():
    params = parse_query_params(default_sort="updated_at")
    with SessionLocal() as s:
        query = apply_query(
            s.query(ChatSession).filter_by(user_id=g.user["id"]),
            ChatSession,
            params,
            searchable=["title", "summary"],
        )
        rows, meta = paginate(query, params)
        return ok([r.to_dict() for r in rows], meta)


@api_bp.get("/sessions/<session_id>/messages")
@require_auth
def list_messages(session_id: str):
    if not sessions.get_session(session_id, g.user["id"]):
        return fail("not_found", "Session not found", 404)
    params = parse_query_params(default_sort="created_at")
    params.order = "asc"
    with SessionLocal() as s:
        query = apply_query(
            s.query(ChatMessage).filter_by(session_id=session_id),
            ChatMessage,
            params,
            searchable=["content"],
        )
        rows, meta = paginate(query, params)
        return ok([r.to_dict() for r in rows], meta)


@api_bp.delete("/sessions/<session_id>")
@require_auth
def delete_session(session_id: str):
    if not sessions.delete_session(session_id, g.user["id"]):
        return fail("not_found", "Session not found", 404)
    return ok({"deleted": session_id})


# --- documents / knowledge base ---------------------------------------------


@api_bp.post("/documents/upload")
@require_auth
@require_role("admin", "analyst")
@rate_limit(per_minute=20)
def upload_document():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return fail("validation_error", "file is required", 422)

    filename = secure_filename(uploaded.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        return fail("unsupported_type", f"{suffix} is not an accepted file type", 415)

    settings.ensure_dirs()
    destination = settings.UPLOAD_DIR / filename
    uploaded.save(destination)

    roles = [r for r in (request.form.get("allowed_roles", "") or "").split(",") if r]
    result = rag_indexer.index_file(
        destination,
        user_id=g.user["id"],
        allowed_roles=roles or ["admin"],
        sensitivity=request.form.get("sensitivity", "internal"),
    )
    return ok(result)


@api_bp.post("/documents/text")
@require_auth
@require_role("admin", "analyst")
@rate_limit(per_minute=20)
def ingest_text():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return fail("validation_error", "text is required", 422)
    result = rag_indexer.index_text(
        body.get("filename", "pasted.txt"),
        text,
        user_id=g.user["id"],
        allowed_roles=body.get("allowed_roles") or ["admin"],
        sensitivity=body.get("sensitivity", "internal"),
    )
    return ok(result)


@api_bp.get("/documents")
@require_auth
def list_documents():
    params = parse_query_params()
    with SessionLocal() as s:
        query = apply_query(s.query(Document), Document, params, searchable=["filename", "source"])
        rows, meta = paginate(query, params)
        return ok([r.to_dict() for r in rows], meta)


@api_bp.delete("/documents/<doc_id>")
@require_auth
@require_role("admin")
def delete_document(doc_id: str):
    removed = rag_indexer.delete_document(doc_id, user_id=g.user["id"])
    return ok({"deleted": doc_id, "chunks_removed": removed})


@api_bp.post("/search")
@require_auth
@rate_limit()
def search():
    """Retrieval only — no generation.

    Returns per-chunk ranking detail (vector rank, keyword rank, rerank score), which
    is the fastest way to show what the retrieval layer is actually doing.
    """
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return fail("validation_error", "query is required", 422)

    chunks = retrieve(
        query,
        user=g.user,
        filters=body.get("filters") or {},
        top_k=int(body.get("top_k") or settings.FINAL_TOP_K),
        decompose=bool(body.get("decompose")),
    )
    audit.record("search.performed", user_id=g.user["id"], results=len(chunks))
    return ok(
        [c.model_dump() for c in chunks],
        {"count": len(chunks), "mode": settings.RETRIEVAL_MODE},
    )


# --- tickets ------------------------------------------------------------------


def _scope_ticket_query(query, user: dict):
    """Same rule as retrieval's ACL, applied to the SQL side: admin/manager (or
    anyone holding the "all" clearance) see every team's tickets; an engineer
    sees only the teams in their own clearances. Scoped in the query, never by
    filtering rows in Python afterwards — the same principle
    guardrails/governance/access_control.py applies to the vector store."""
    role = user.get("role", "viewer")
    clearances = user.get("clearances") or []
    if role in ("admin", "manager") or "all" in clearances:
        return query
    teams = [c for c in clearances if c in settings.TEAMS]
    return query.filter(Ticket.assigned_team.in_(teams)) if teams else query.filter(False)


@api_bp.post("/tickets")
@require_auth
@rate_limit(per_minute=30)
def create_ticket():
    """Live triage: paste/submit a ticket, run it through the full graph, get a
    routed decision back. Open to any authenticated user — the manager-only gate
    is on *approving* a decision (POST /tickets/<id>/approve), not on submitting
    one for triage."""
    payload, error = validate_request(request.get_json(silent=True), TicketIngestRequest)
    if error:
        return fail("validation_error", error, 422)

    row, state = ingest_and_triage(payload.model_dump(), g.user)
    decision = state.get("decision")
    return ok(
        {
            "ticket": row.to_dict(),
            "decision": decision.model_dump() if decision else None,
            "blocked": state.get("blocked", False),
            "blocked_reason": state.get("blocked_reason", ""),
            "guardrails_fired": state.get("guardrails_fired") or [],
        },
        {"status": row.status},
    )


@api_bp.get("/tickets")
@require_auth
def list_tickets():
    params = parse_query_params()
    with SessionLocal() as s:
        query = _scope_ticket_query(s.query(Ticket), g.user)
        query = apply_query(query, Ticket, params, searchable=["external_id", "title"])
        rows, meta = paginate(query, params)
        return ok([r.to_dict() for r in rows], meta)


@api_bp.get("/teams/queue")
@require_auth
def team_queue():
    """The engineer console's queue — open tickets only, same ACL scoping as
    /tickets. filter[status] still works for a manager who wants one team's open
    items without the closed history."""
    params = parse_query_params()
    with SessionLocal() as s:
        query = _scope_ticket_query(s.query(Ticket), g.user)
        query = query.filter(Ticket.status.notin_(["resolved", "synced"]))
        query = apply_query(query, Ticket, params, searchable=["external_id", "title"])
        rows, meta = paginate(query, params)
        return ok([r.to_dict() for r in rows], meta)


@api_bp.get("/tickets/<ticket_id>")
@require_auth
def get_ticket(ticket_id: str):
    with SessionLocal() as s:
        row = s.get(Ticket, ticket_id)
        if not row:
            return fail("not_found", "Ticket not found", 404)
        if _scope_ticket_query(s.query(Ticket).filter_by(id=ticket_id), g.user).first() is None:
            # Exists, but not on this user's team — 404, not 403, so the queue
            # never leaks which ids exist outside a user's ACL scope.
            return fail("not_found", "Ticket not found", 404)
        runs = (
            s.query(TriageRun)
            .filter_by(ticket_id=ticket_id)
            .order_by(TriageRun.created_at.desc())
            .limit(5)
            .all()
        )
        return ok({"ticket": row.to_dict(), "runs": [r.to_dict() for r in runs]})


@api_bp.patch("/tickets/<ticket_id>/override")
@require_auth
def override_ticket(ticket_id: str):
    """Manager or engineer-on-their-own-team can override a field. Reason is
    mandatory (OverrideRequest enforces min_length=3) — every override is both
    audited and queued as feedback, so it feeds the eval set the same way a
    thumbs-down on a chat answer does."""
    payload, error = validate_request(request.get_json(silent=True), OverrideRequest)
    if error:
        return fail("validation_error", error, 422)

    with SessionLocal() as s:
        row = s.get(Ticket, ticket_id)
        if not row:
            return fail("not_found", "Ticket not found", 404)
        if _scope_ticket_query(s.query(Ticket).filter_by(id=ticket_id), g.user).first() is None:
            return fail("not_found", "Ticket not found", 404)

        setattr(row, payload.field, payload.new_value)
        row.overridden_by = g.user["id"]
        row.override_reason = payload.reason
        s.commit()
        s.refresh(row)

        audit.record(
            "ticket.overridden",
            user_id=g.user["id"],
            resource=ticket_id,
            field=payload.field,
            new_value=payload.new_value,
            reason=payload.reason,
        )
        # Feeds the eval set the same way a chat thumbs-down does — a message_id
        # is required by the Feedback table, so the ticket id doubles as one here.
        s.add(
            Feedback(
                message_id=ticket_id,
                user_id=g.user["id"],
                rating=-1,
                comment=f"override {payload.field} -> {payload.new_value}: {payload.reason}",
            )
        )
        s.commit()
        return ok(row.to_dict())


@api_bp.post("/tickets/<ticket_id>/approve")
@require_auth
@require_role("admin", "manager")
def approve_ticket(ticket_id: str):
    """The human-in-the-loop gate's other half. Sets status to "approved" *then*
    calls tools.ticket_update — the tool itself re-checks that status before
    writing anything, so this route cannot accidentally bypass the gate by
    calling the ticket source directly."""
    with SessionLocal() as s:
        row = s.get(Ticket, ticket_id)
        if not row:
            return fail("not_found", "Ticket not found", 404)

        row.status = "approved"
        s.commit()
        s.refresh(row)

        fields = {
            "severity": row.severity,
            "priority_score": row.priority_score,
            "assigned_team": row.assigned_team,
            "confidence": row.confidence,
        }

    try:
        result = tools.call(
            "ticket_update",
            ticket_id,
            fields,
            user=g.user,
            ticket_status="approved",
            confidence=row.confidence,
            severity=row.severity,
        )
    except ToolDenied as exc:
        return fail("tool_denied", str(exc), 403)

    try:
        source = tools.get_ticket_source()
        source.add_comment(
            ticket_id,
            f"TicketSphere: {row.severity} · {row.assigned_team} · "
            f"priority {row.priority_score} · confidence {row.confidence:.0%}. "
            f"Approved by {g.user.get('username', g.user['id'])}.",
        )
        source.transition(ticket_id, "routed")
    except Exception as exc:  # noqa: BLE001 - comment/transition failure must not lose the approval
        log.warning("post-approval comment/transition failed for %s: %s", ticket_id, exc)

    with SessionLocal() as s:
        row = s.get(Ticket, ticket_id)
        row.status = "routed"
        row.needs_human = False
        s.commit()
        s.refresh(row)

    audit.record("ticket.approved", user_id=g.user["id"], resource=ticket_id, **result)
    return ok(row.to_dict())


# --- integrations -------------------------------------------------------------


@api_bp.post("/integrations/sync")
@require_auth
@require_role("admin", "manager")
@rate_limit(per_minute=6)
def integrations_sync():
    """Manually trigger one poll cycle now, instead of waiting for the
    JIRA_POLL_SECONDS timer — the demo control for "show me it pulling live"."""
    result = poll_once()
    audit.record("integrations.sync", user_id=g.user["id"], **result)
    return ok(result, {"watermark": get_watermark()})


@api_bp.post("/integrations/webhook")
def integrations_webhook():
    """Receiver for a Jira Automation "issue created/updated -> send web request"
    rule. Not the primary sync path — see integrations/jira.py's module
    docstring — demoed with a local curl rather than a live rule, since the AI
    Lab's laptops have no public URL for Jira to reach. Deliberately unauthenticated
    (Jira Automation webhooks are not easily made to carry a bearer token); if this
    ever faces a real network, put it behind a shared-secret header check.
    """
    body = request.get_json(silent=True) or {}
    issue = body.get("issue") or body
    fields = issue.get("fields") or {}

    from integrations.jira import adf_to_text

    raw = {
        "external_id": issue.get("key", ""),
        "source": "jira",
        "title": fields.get("summary", ""),
        "body": adf_to_text(fields.get("description")) or fields.get("description", ""),
        "application": "",
        "environment": "prod",
        "channel": "jira-webhook",
        "raw": body,
    }
    if not raw["external_id"] or not raw["title"]:
        return fail("validation_error", "issue.key and fields.summary are required", 422)

    system_user = {"id": "system:webhook", "role": "admin", "clearances": ["all"]}
    row, state = ingest_and_triage(raw, system_user)
    audit.record("integrations.webhook_received", resource=row.id, external_id=row.external_id)
    return ok({"ticket_id": row.id, "status": row.status, "blocked": state.get("blocked", False)})


# --- feedback / human-in-the-loop -------------------------------------------


@api_bp.post("/feedback")
@require_auth
def submit_feedback():
    payload, error = validate_request(request.get_json(silent=True), FeedbackRequest)
    if error:
        return fail("validation_error", error, 422)
    with SessionLocal() as s:
        entry = Feedback(
            message_id=payload.message_id,
            user_id=g.user["id"],
            rating=payload.rating,
            comment=payload.comment,
            corrected_answer=payload.corrected_answer,
        )
        s.add(entry)
        s.commit()
        audit.record(
            "feedback.submitted",
            user_id=g.user["id"],
            resource=payload.message_id,
            rating=payload.rating,
        )
        return ok(entry.to_dict())


@api_bp.get("/feedback")
@require_auth
@require_role("admin", "analyst")
def list_feedback():
    """The HITL review queue — filter[reviewed]=false for the open items."""
    params = parse_query_params()
    with SessionLocal() as s:
        query = apply_query(s.query(Feedback), Feedback, params, searchable=["comment"])
        rows, meta = paginate(query, params)
        return ok([r.to_dict() for r in rows], meta)


@api_bp.patch("/feedback/<feedback_id>/review")
@require_auth
@require_role("admin", "analyst")
def review_feedback(feedback_id: str):
    with SessionLocal() as s:
        entry = s.get(Feedback, feedback_id)
        if not entry:
            return fail("not_found", "Feedback not found", 404)
        entry.reviewed = True
        body = request.get_json(silent=True) or {}
        if body.get("corrected_answer"):
            entry.corrected_answer = body["corrected_answer"]
        s.commit()
        audit.record("feedback.reviewed", user_id=g.user["id"], resource=feedback_id)
        return ok(entry.to_dict())


# --- observability ----------------------------------------------------------


@api_bp.get("/analytics/usage")
@require_auth
def analytics_usage():
    with SessionLocal() as s:
        totals = {
            "sessions": s.query(ChatSession).count(),
            "messages": s.query(ChatMessage).count(),
            "documents": s.query(Document).count(),
            "chunks": vector_store.count(),
            "feedback_positive": s.query(Feedback).filter_by(rating=1).count(),
            "feedback_negative": s.query(Feedback).filter_by(rating=-1).count(),
        }
    return ok({**usage_summary(), **totals})


@api_bp.get("/analytics/traces")
@require_auth
def analytics_traces():
    params = parse_query_params()
    return ok(recent_traces(params.page_size))


@api_bp.get("/analytics/messages")
@require_auth
def analytics_messages():
    """Per-message latency / tokens / groundedness — the series the charts use."""
    with SessionLocal() as s:
        rows = (
            s.query(ChatMessage)
            .filter(ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc())
            .limit(100)
            .all()
        )
    return ok([r.to_dict() for r in reversed(rows)])


# --- evals ------------------------------------------------------------------


@api_bp.post("/evals/run")
@require_auth
@require_role("admin", "analyst")
@rate_limit(per_minute=3)
def run_evals():
    body = request.get_json(silent=True) or {}
    result = evals.run_eval_set(g.user, questions=body.get("questions"))
    audit.record("evals.run", user_id=g.user["id"], cases=result["cases"])
    return ok(result)


@api_bp.get("/evals")
@require_auth
def list_evals():
    params = parse_query_params()
    with SessionLocal() as s:
        query = apply_query(s.query(EvalResult), EvalResult, params, searchable=["question"])
        rows, meta = paginate(query, params)
        return ok([r.to_dict() for r in rows], meta)


# --- governance -------------------------------------------------------------


@api_bp.get("/audit")
@require_auth
@require_role("admin")
def list_audit():
    params = parse_query_params()
    with SessionLocal() as s:
        query = apply_query(s.query(AuditLog), AuditLog, params, searchable=["action", "resource"])
        rows, meta = paginate(query, params)
        return ok([r.to_dict() for r in rows], meta)


@api_bp.get("/audit/verify")
@require_auth
@require_role("admin")
def verify_audit():
    return ok(audit.verify_chain())


# --- errors -----------------------------------------------------------------


@api_bp.errorhandler(Exception)
def unhandled(exc: Exception):
    log.exception("unhandled error on %s", request.path)
    return fail("internal_error", "Something went wrong. Check the server log.", 500)
