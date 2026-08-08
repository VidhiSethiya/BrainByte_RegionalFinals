"""Assembles prompts and runs conversational (non-RAG) LLM turns.

Priority when the budget is tight:
    system persona > current question > retrieved/ticket context > rolling summary > history
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ai.llm import chat_json, chat_messages
from ai.prompts import ANSWER_PROMPT, SUGGEST_FOLLOWUPS_PROMPT, SYSTEM_PERSONA
from config import settings
from db.sqlite.models import ChatMessage, SessionLocal
from observability.telemetry import log
from rag.rag_retriever import build_context
from rag.schemas import RetrievedChunk, normalize_severity
from sqlalchemy import text

MAX_CONTEXT_CHARS = 6000
CHARS_PER_TOKEN = 4
TITLE_CHARS = 60

# Conversational system add-on (chatbot-owned; prompts.py is owned by another team).
_CONVERSATIONAL_SYSTEM = (
    SYSTEM_PERSONA
    + """

Additional rules for live conversation:
- Greetings and small-talk: reply warmly and naturally in 1-3 sentences. Do not refuse
  for lack of documents. Offer to help with tickets, SLAs, or runbooks.
- Questions about earlier turns ("what did I ask", "what was my last question"): answer
  from CONVERSATION HISTORY / SUMMARY only. Quote briefly if helpful.
- When TICKET DATA is provided, treat it as authoritative SQL facts. Answer from it.
  Do not invent ticket IDs, severities, or counts that are not in TICKET DATA.
- confidence in TICKET DATA is the model's own triage confidence for that ticket —
  never invent a different number (e.g. reporting 100%/1.0 because a row matched
  the user's filter is wrong; that is not what "confidence" means here).
- open_for in TICKET DATA is real elapsed time since the ticket was created —
  never claim there is no age/timestamp data available; if the user asked for an
  age-based filter ("open for more than N hours") it was already applied in the
  query, so every row shown already matches it.
- You cannot approve, reassign, or otherwise write to a ticket yourself — you have
  no tool for it. If asked to "approve X", identify the ticket(s) from TICKET DATA
  by name and status, then tell the user to use the "Bulk approve & route" button
  under this answer (admin-only) or the ticket's own Approve action — never claim
  you can't find a ticket that legitimately appears in TICKET DATA just because
  approving isn't something you can do.
- Stay conversational and two-way: acknowledge the user, answer, and invite a follow-up.
"""
)

_GREETING_EXACT = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hiya",
        "howdy",
        "good morning",
        "good afternoon",
        "good evening",
        "good night",
        "how are you",
        "how are you doing",
        "how's it going",
        "hows it going",
        "what's up",
        "whats up",
        "sup",
        "yo",
        "greetings",
        "hi there",
        "hello there",
        "hey there",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "bye",
        "goodbye",
    }
)

_GREETING_PREFIXES = (
    "hi ",
    "hello ",
    "hey ",
    "good morning",
    "good afternoon",
    "good evening",
    "how are you",
    "thanks ",
    "thank you",
)

_MEMORY_PATTERNS = (
    r"\bwhat did i (just )?(ask|say|mean)\b",
    r"\bwhat was (my|the) (last|previous|earlier) (question|message|ask)\b",
    r"\bwhat did i just say\b",
    r"\bremind me what i\b",
    r"\bmy (last|previous|earlier) (question|message)\b",
    r"\bwhat were we (talking|discussing)\b",
    r"\bcan you (repeat|recall|remember)\b",
    r"\bas i (said|asked|mentioned)\b",
    r"\bearlier (i|you|we)\b",
    r"\bprevious (message|question|turn)\b",
)

# \d{3,} previously required 3+ digits, matching only the zero-padded synthetic
# seed IDs (INC0000001). The real live Jira board numbers issues INC-1..INC-63 —
# 1-2 digits — which silently never matched at all, so "approve INC-52" or any
# reference to a real low-numbered ticket fell through to the general KB search
# instead of the live ticket table. The prefix + required separator already
# rules out matching an unrelated bare number, so \d+ is safe.
_TICKET_ID_RE = re.compile(r"\b((?:INC|CHG|REQ|PRB|TKT)[-_]?\d+)\b", re.I)
_TEAM_RE = re.compile(r"\b(ops|azure|aws|gcp)\b", re.I)
# Legacy S1-4/P1-4 codes AND the actual Jira Priority names the rest of the
# system speaks (tickets.severity stores "Highest"/"High"/"Medium"/"Low", never
# a code) — this regex previously only recognized the codes, so "highest
# priority incidents" or "priority as highest" never registered as a severity
# mention at all.
_SEVERITY_RE = re.compile(r"\b(S[1-4]|sev(?:erity)?\s*[1-4]|p[1-4]|highest|high|medium|low)\b", re.I)
# "ticket(s)" was previously the only noun this function recognized — "issues"
# and "incidents" (both common ways people actually ask for the same thing,
# see the unused _TICKET_INTENT_RE this replaces below) fell through to the
# general KB/RAG path instead of the live ticket table.
_TICKET_NOUN_RE = re.compile(r"\b(tickets?|issues?|incidents?)\b", re.I)
# "open for more than 8 hours" / "older than 2 days" / "less than 30 minutes" —
# a real gap: nothing parsed a duration at all, so the SQL path had no way to
# filter or report ticket age and would tell the user it had no timestamps
# (untrue; every ticket has created_at, this function just never read one out).
_AGE_RE = re.compile(
    r"\b(more than|older than|over|at least|greater than|"
    r"less than|under|within|younger than)\s+(\d+)\s*"
    r"(hour|hours|hr|hrs|day|days|minute|minutes|min|mins)\b",
    re.I,
)
_AGE_GTE_WORDS = {"more than", "older than", "over", "at least", "greater than"}
_AGE_UNIT_MINUTES = {"hour": 60, "hr": 60, "day": 1440, "minute": 1, "min": 1}


def _age_unit_minutes(unit: str) -> int:
    key = unit.lower().rstrip("s")
    return _AGE_UNIT_MINUTES.get(key, 60)


def fit_chunks(chunks: list[RetrievedChunk], budget: int = MAX_CONTEXT_CHARS) -> list[RetrievedChunk]:
    kept: list[RetrievedChunk] = []
    used = 0
    for chunk in chunks:
        cost = len(chunk.text) + 60
        if used + cost > budget:
            continue
        kept.append(chunk)
        used += cost
    return kept


def build_messages(
    question: str,
    chunks: list[RetrievedChunk],
    summary: str = "",
    history: list[ChatMessage] | None = None,
) -> tuple[list, str]:
    fitted = fit_chunks(chunks)
    context = build_context(fitted) if fitted else "(no relevant documents found)"

    messages: list = [SystemMessage(content=SYSTEM_PERSONA)]

    for message in history or []:
        if message.role == "user":
            messages.append(HumanMessage(content=message.content[:1000]))
        elif message.role == "assistant" and not message.blocked_reason:
            messages.append(AIMessage(content=message.content[:1000]))

    messages.append(
        HumanMessage(
            content=ANSWER_PROMPT.format(
                context=context,
                summary=summary or "(new conversation)",
                question=question,
                domain=settings.DOMAIN,
            )
        )
    )
    return messages, context


def estimate_tokens(messages: list) -> int:
    return sum(len(str(m.content)) for m in messages) // CHARS_PER_TOKEN


def suggest_followups(summary: str, answer: str, trace=None) -> list[str]:
    try:
        result = chat_json(
            SUGGEST_FOLLOWUPS_PROMPT.format(
                summary=summary or "(none)",
                answer=(answer or "")[:1200],
            ),
            fast=True,
            trace=trace,
            default={},
        )
        return [s for s in (result or {}).get("suggestions", []) if isinstance(s, str)][:3]
    except Exception as exc:  # noqa: BLE001
        log.warning("follow-up suggestions failed: %s", exc)
        return []


def infer_title(first_message: str, answer: str = "") -> str:
    text = (first_message or "").strip()
    if not text:
        return "New conversation"
    line = text.split("\n", 1)[0].strip().rstrip("?.!")
    if len(line) > TITLE_CHARS:
        line = line[: TITLE_CHARS - 1].rstrip() + "…"
    return line or "New conversation"


def under_budget(messages: list, max_tokens: int | None = None) -> bool:
    budget = max_tokens or (MAX_CONTEXT_CHARS // CHARS_PER_TOKEN)
    return estimate_tokens(messages) <= budget


def is_greeting(text: str) -> bool:
    """Heuristic router only — the reply itself is always LLM-generated."""
    cleaned = " ".join((text or "").strip().lower().split())
    cleaned = cleaned.rstrip("!?.,;: ")
    if not cleaned or len(cleaned) > 100:
        return False
    if cleaned in _GREETING_EXACT:
        return True
    return any(cleaned.startswith(p) for p in _GREETING_PREFIXES) and len(cleaned.split()) <= 10


def is_memory_question(text: str) -> bool:
    """User is asking about prior turns in this session."""
    cleaned = " ".join((text or "").strip().lower().split())
    return any(re.search(p, cleaned) for p in _MEMORY_PATTERNS)


def looks_like_ticket_query(text: str) -> bool:
    """True for live ticket-table questions (counts, lists, INC ids) — not KB/SLA docs."""
    raw = text or ""
    if _TICKET_ID_RE.search(raw):
        return True
    lower = raw.lower()
    # Policy / runbook / SLA prose belongs in RAG, not the tickets table.
    kb_markers = (
        "sla ",
        " sla",
        "runbook",
        "policy",
        "escalation",
        "service catalogue",
        "service catalog",
        "precedent",
        "how do i",
        "how to fix",
        "how to resolve",
    )
    if any(m in lower for m in kb_markers) and "how many" not in lower and "list ticket" not in lower:
        return False

    sql_markers = (
        "how many ticket",
        "how many open",
        "count ticket",
        "number of ticket",
        "list ticket",
        "list the ticket",
        "show ticket",
        "show me ticket",
        "open tickets",
        "ticket status",
        "tickets assigned",
        "tickets for",
        "tickets in",
        "tickets on",
        "my tickets",
        "queue for",
        "assigned to",
    )
    if any(m in lower for m in sql_markers):
        return True
    if _TICKET_NOUN_RE.search(raw) and (_TEAM_RE.search(raw) or _SEVERITY_RE.search(raw) or _AGE_RE.search(raw)):
        action_words = (
            "list", "show", "count", "how many", "status", "assigned", "open",
            "fetch", "get", "give", "provide", "pull", "find", "all",
        )
        if any(m in lower for m in action_words):
            return True
    return False


def _build_ticket_where(
    question: str, limit: int
) -> tuple[str, dict[str, object], list[str], bool, bool]:
    """Shared filter parsing behind both fetch_ticket_context (narration) and
    fetch_approvable_tickets (the chat bulk-approve action) — one parse of
    "P1", "azure", "INC-123" etc. out of the free-text question, reused for
    both queries so the two never drift apart on what "matches"."""
    q = question or ""
    ids = [m.group(1).upper().replace("_", "-") for m in _TICKET_ID_RE.finditer(q)]
    teams = [m.group(1).lower() for m in _TEAM_RE.finditer(q)]
    # tickets.severity stores Jira Priority names (Highest/High/Medium/Low), never
    # the S1-S4/P1-P4 shorthand a user actually types — normalize_severity() maps
    # "P1"/"S1"/"sev1" onto "Highest" etc. so this filter matches real rows.
    sev_raw = [m.group(1).upper().replace(" ", "") for m in _SEVERITY_RE.finditer(q)]
    severities: list[str] = []
    for s in sev_raw:
        code = s
        if code.startswith("SEV"):
            code = "S" + code[-1]
        elif code.startswith("P"):
            code = "S" + code[-1]
        elif code.startswith("S"):
            code = code[:2]
        jira_name = normalize_severity(code)
        if jira_name:
            severities.append(jira_name.upper())

    want_count = bool(re.search(r"\b(how many|count|number of)\b", q, re.I))
    where: list[str] = ["1=1"]
    params: dict[str, object] = {"limit": limit}

    if teams:
        placeholders = []
        for i, team in enumerate(teams):
            key = f"team{i}"
            placeholders.append(f":{key}")
            params[key] = team
        where.append(f"lower(coalesce(assigned_team,'')) in ({', '.join(placeholders)})")
    if severities:
        placeholders = []
        for i, sev in enumerate(severities):
            key = f"sev{i}"
            placeholders.append(f":{key}")
            params[key] = sev
        where.append(f"upper(coalesce(severity,'')) in ({', '.join(placeholders)})")
    if ids:
        id_clauses = []
        for i, tid in enumerate(ids):
            key = f"id{i}"
            id_clauses.append(f"(upper(coalesce(external_id,'')) like :{key} or id = :{key}_exact)")
            params[key] = f"%{tid}%"
            params[f"{key}_exact"] = tid
        where.append("(" + " OR ".join(id_clauses) + ")")

    age_match = _AGE_RE.search(q)
    has_age_filter = bool(age_match)
    if age_match:
        direction, amount, unit = age_match.group(1).lower(), int(age_match.group(2)), age_match.group(3)
        minutes = amount * _age_unit_minutes(unit)
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes)
        if direction in _AGE_GTE_WORDS:
            # "open for more than N hours" -> created at or before (now - N) -> older than N.
            where.append("created_at <= :age_cutoff")
        else:
            # "open for less than N hours" -> created after (now - N) -> younger than N.
            where.append("created_at >= :age_cutoff")
        params["age_cutoff"] = cutoff.isoformat(sep=" ")

    has_filters = bool(ids or teams or severities or has_age_filter)
    return " AND ".join(where), params, ids, want_count, has_filters


def fetch_approvable_tickets(question: str, limit: int = 20) -> list[dict]:
    """Same filters as fetch_ticket_context, narrowed to tickets that are
    actually ready for POST /tickets/bulk-approve: triage finished (severity +
    team set) and not already approved/routed/resolved/synced/failed.

    This is the read side of the chat bulk-approve flow — it only ever lists
    candidates. Nothing here writes; the admin still has to click the button
    that calls bulk_approve_tickets, and that route (not this function)
    re-checks role and re-runs the same "is this ready" gate per ticket."""
    where_sql, params, _ids, _want_count, _has_filters = _build_ticket_where(question, limit)
    try:
        with SessionLocal() as s:
            rows = s.execute(
                text(
                    f"SELECT id, external_id, title, severity, assigned_team, status "
                    f"FROM tickets WHERE {where_sql} "
                    f"AND coalesce(severity,'') != '' AND coalesce(assigned_team,'') != '' "
                    f"AND status NOT IN ('approved','routed','resolved','synced','failed') "
                    f"ORDER BY updated_at DESC LIMIT :limit"
                ),
                params,
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - never take down the chat turn
        log.warning("fetch_approvable_tickets failed: %s", exc)
        return []
    return [
        {
            "id": tid,
            "external_id": ext or "",
            "title": title or "",
            "severity": sev or "",
            "assigned_team": team or "",
        }
        for tid, ext, title, sev, team, _status in rows
    ]


def fetch_ticket_context(question: str, limit: int = 12) -> str:
    """Pull live ticket rows from SQLite to ground ticket Q&A.

    Uses raw SQL against columns that exist in app.db (avoids ORM drift when
    models.py gains columns the local SQLite file does not have yet).
    """
    where_sql, params, ids, want_count, has_filters = _build_ticket_where(question, limit)
    lines: list[str] = []

    try:
        with SessionLocal() as s:
            if want_count and not ids:
                total = s.execute(
                    text(f"SELECT count(*) FROM tickets WHERE {where_sql}"),
                    params,
                ).scalar() or 0
                lines.append(f"COUNT: {total} ticket(s) match the filters.")
                for label, col in (
                    ("BY_SEVERITY", "severity"),
                    ("BY_TEAM", "assigned_team"),
                    ("BY_STATUS", "status"),
                ):
                    rows = s.execute(
                        text(
                            f"SELECT coalesce({col},'unset'), count(*) "
                            f"FROM tickets WHERE {where_sql} GROUP BY {col}"
                        ),
                        params,
                    ).fetchall()
                    if rows:
                        lines.append(
                            f"{label}: " + ", ".join(f"{k}={n}" for k, n in rows)
                        )
            else:
                rows = s.execute(
                    text(
                        f"SELECT external_id, id, assigned_team, severity, status, confidence, "
                        f"created_at, title, substr(coalesce(body_masked,''), 1, 240) "
                        f"FROM tickets WHERE {where_sql} "
                        f"ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    params,
                ).fetchall()
                if not rows and not has_filters:
                    rows = s.execute(
                        text(
                            "SELECT external_id, id, assigned_team, severity, status, confidence, "
                            "created_at, title, substr(coalesce(body_masked,''), 1, 240) "
                            "FROM tickets ORDER BY updated_at DESC LIMIT :limit"
                        ),
                        {"limit": min(limit, 8)},
                    ).fetchall()
                lines.append(f"MATCHED_ROWS: {len(rows)}")
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                # confidence is the model's own triage confidence (0-1, stored per
                # ticket) — not "how well this row matches your filter" (that's
                # always 1.0 for anything that made it through the WHERE clause
                # and isn't a useful number to report). age_open is real elapsed
                # time since created_at (the incident's actual start — see
                # ai/agents.py::ingest_and_triage for where that's set from Jira's
                # "created" field). Neither was selected before, so the model had
                # nothing real to cite for either and would either invent a number
                # or claim it had no timestamps at all — untrue, it just wasn't
                # given one.
                for ext, tid, team, sev, status, confidence, created_at, title, body in rows:
                    body_one = (body or "").replace("\n", " ")
                    conf_pct = f"{confidence * 100:.0f}%" if confidence is not None else "-"
                    if created_at:
                        created_dt = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at))
                        age_hours = (now - created_dt).total_seconds() / 3600
                        age_str = f"{age_hours:.1f}h"
                    else:
                        age_str = "-"
                    lines.append(
                        f"- {ext or tid} | team={team or '-'} | sev={sev or '-'} | "
                        f"status={status or '-'} | confidence={conf_pct} | open_for={age_str} | "
                        f"title={title or '-'} | body={body_one}"
                    )
    except Exception as exc:  # noqa: BLE001 - never take down the chat turn
        log.warning("ticket SQL lookup failed: %s", exc)
        return (
            "TICKET DATA\n(ticket database unavailable or schema mismatch — "
            f"{type(exc).__name__}: {exc})"
        )

    if not lines or (len(lines) == 1 and lines[0].startswith("MATCHED_ROWS: 0")):
        return "TICKET DATA\n(no matching tickets in the database)"
    return "TICKET DATA\n" + "\n".join(lines)


def build_conversational_messages(
    question: str,
    *,
    summary: str = "",
    history: list[ChatMessage] | None = None,
    ticket_context: str = "",
    user: dict | None = None,
) -> list:
    """Messages for greeting / memory / ticket-SQL conversational turns."""
    messages: list = [SystemMessage(content=_CONVERSATIONAL_SYSTEM)]

    for message in history or []:
        if message.role == "user":
            messages.append(HumanMessage(content=message.content[:1200]))
        elif message.role == "assistant" and not getattr(message, "blocked_reason", None):
            messages.append(AIMessage(content=message.content[:1200]))

    username = (user or {}).get("username") or ""
    parts = [
        f"USER_NAME: {username or '(unknown)'}",
        f"CONVERSATION SUMMARY:\n{summary or '(new conversation)'}",
    ]
    if ticket_context:
        parts.append(ticket_context)
    parts.append(f"USER MESSAGE:\n{question}")
    parts.append(
        "Respond as TicketSphere in a natural conversational style. "
        "Use history/summary for continuity. Use TICKET DATA when present."
    )
    messages.append(HumanMessage(content="\n\n".join(parts)))
    return messages


def conversational_reply(
    question: str,
    *,
    summary: str = "",
    history: list[ChatMessage] | None = None,
    ticket_context: str = "",
    user: dict | None = None,
    trace=None,
) -> str:
    """LLM reply for greetings, memory questions, and ticket-SQL grounded chat."""
    messages = build_conversational_messages(
        question,
        summary=summary,
        history=history,
        ticket_context=ticket_context,
        user=user,
    )
    try:
        if trace is not None:
            with trace.stage("conversational_llm"):
                return (chat_messages(messages, trace=trace) or "").strip()
        return (chat_messages(messages, trace=trace) or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("conversational_reply failed: %s", exc)
        return (
            "I'm having trouble reaching the language model right now. "
            "Please try again in a moment."
        )


def greeting_suggestions() -> list[str]:
    return [
        "What is the SLA for S1 tickets?",
        "How many open tickets are assigned to Azure?",
        "What did I ask in my previous message?",
    ]
