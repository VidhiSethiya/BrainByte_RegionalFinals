"""The tool registry every agent node may call, and the single choke point that
enforces write scope.

Read tools are open to any authenticated role (`requires_role=None`) or gated to
one role (`ticket_stats` is manager/admin only — it backs the manager chatbot's
"how many S1 this week" answers, and an engineer has no legitimate reason to pull
cross-team aggregates). The one write tool, `ticket_update`, refuses unless the
ticket's decision is already approved or the auto-approval band applies
(confidence >= 0.85 AND severity in {S3, S4}) — this is where that rule is
actually *enforced*, not just previewed the way ai/agents.py::triage_sync's status
bookkeeping does. A refusal is audited as `tool.denied`, never silently swallowed.

Call every tool through `call()`, not the bare function — that is what makes the
role check and the audit trail unconditional rather than a convention someone
forgets.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import settings
from db.sqlite.models import SessionLocal, Ticket as TicketRow
from guardrails.governance import audit
from observability.telemetry import log
from rag.rag_retriever import retrieve
from rag.schemas import TicketStats

# Mirrors ai/agents.py::AUTO_APPROVE_CONFIDENCE / AUTO_APPROVE_SEVERITIES. Kept as
# a second copy rather than importing from agents.py — this module must not
# depend on the graph, only the graph (and the API layer) depend on this. If you
# change one, change both; there is no automated check (this project ships no
# test suite, CLAUDE.md golden rule 3), so this comment is the whole guardrail.
AUTO_APPROVE_CONFIDENCE = 0.85
AUTO_APPROVE_SEVERITIES = {"S3", "S4"}


class ToolDenied(RuntimeError):
    pass


# --- read tools ---------------------------------------------------------------


def kb_search(query: str, top_k: int = 6, user: dict | None = None) -> list[dict]:
    chunks = retrieve(query, user=user or {}, top_k=top_k)
    return [c.model_dump() for c in chunks]


def similar_tickets(query: str, top_k: int = 5, user: dict | None = None) -> list[dict]:
    chunks = retrieve(
        query,
        user=user or {},
        filters={"doc_type": "ticket_history", "resolved": "true"},
        top_k=top_k,
    )
    return [c.model_dump() for c in chunks]


def team_capacity(user: dict | None = None) -> dict[str, dict]:
    """Deterministic SQL aggregate — open ticket count and oldest-open age per
    team. No LLM involved; this is a real number, not a generated estimate."""
    with SessionLocal() as s:
        rows = (
            s.query(TicketRow)
            .filter(TicketRow.status.in_(["new", "triaged", "awaiting_approval", "routed"]))
            .all()
        )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    by_team: dict[str, dict] = {t: {"open": 0, "oldest_age_mins": 0} for t in settings.TEAMS}
    for row in rows:
        bucket = by_team.setdefault(row.assigned_team or "ops", {"open": 0, "oldest_age_mins": 0})
        bucket["open"] += 1
        age = int((now - row.created_at).total_seconds() / 60) if row.created_at else 0
        bucket["oldest_age_mins"] = max(bucket["oldest_age_mins"], age)
    return by_team


def sla_policy(severity: str, user: dict | None = None) -> list[dict]:
    chunks = retrieve(
        f"SLA target response time for severity {severity}",
        user=user or {},
        filters={"doc_type": "sla_policy"},
        top_k=3,
    )
    return [c.model_dump() for c in chunks]


def ticket_stats(
    from_date: str | None = None,
    to_date: str | None = None,
    user: dict | None = None,
) -> TicketStats:
    """The deterministic aggregate the manager chatbot narrates, never generates.
    See ai/prompts.py::STATS_NARRATE_PROMPT and docs/JUDGES_QA.md 'the LLM never
    counts' — this function is the other half of that claim."""
    with SessionLocal() as s:
        q = s.query(TicketRow)
        if from_date:
            q = q.filter(TicketRow.created_at >= from_date)
        if to_date:
            q = q.filter(TicketRow.created_at <= to_date)
        rows = q.all()

    by_severity: dict[str, int] = {}
    by_team: dict[str, int] = {}
    by_status: dict[str, int] = {}
    sla_at_risk = 0
    awaiting_approval = 0
    for row in rows:
        if row.severity:
            by_severity[row.severity] = by_severity.get(row.severity, 0) + 1
        if row.assigned_team:
            by_team[row.assigned_team] = by_team.get(row.assigned_team, 0) + 1
        by_status[row.status] = by_status.get(row.status, 0) + 1
        if row.status == "awaiting_approval":
            awaiting_approval += 1
        if row.severity == "S1" and row.status not in ("resolved", "synced"):
            sla_at_risk += 1

    return TicketStats(
        total=len(rows),
        by_severity=by_severity,
        by_team=by_team,
        by_status=by_status,
        sla_at_risk=sla_at_risk,
        awaiting_approval=awaiting_approval,
        from_date=from_date,
        to_date=to_date,
    )


def rule_route(application: str, user: dict | None = None) -> str:
    """Deterministic fallback routing — the bottom rung of the degradation ladder
    (deep model -> fast model -> this -> human queue). A keyword match against
    the team name, nothing more; it exists so route() never has no answer at
    all, not to be a good router."""
    app = (application or "").lower()
    for team in settings.TEAMS:
        if team in app:
            return team
    return "ops"


# --- the one write tool -------------------------------------------------------


def ticket_update(
    ticket_id: str,
    fields: dict[str, Any],
    *,
    ticket_status: str,
    confidence: float = 0.0,
    severity: str = "",
    user: dict | None = None,
) -> dict:
    """The only write tool in the system. Refuses unless the decision is already
    approved (ticket_status in {"approved", "routed"} — set by
    POST /tickets/<id>/approve) or the auto-approval band applies. This is the
    actual enforcement point BLUEPRINT.md §5 and rag-handoff.md §8 describe —
    never bypassed by calling JiraSource.update() directly, which is why every
    write path in api.py goes through tools.call("ticket_update", ...), not the
    ticket source's update() method.

    ``ticket_id`` is the SQLite primary key; the adapter always receives
    ``Ticket.external_id`` (Jira key e.g. SCRUM-5).
    """
    approved = ticket_status in ("approved", "routed", "synced")
    auto_approved = (
        not approved
        and confidence >= AUTO_APPROVE_CONFIDENCE
        and severity in AUTO_APPROVE_SEVERITIES
    )
    if not (approved or auto_approved):
        audit.record(
            "tool.denied",
            user_id=(user or {}).get("id"),
            resource=ticket_id,
            tool="ticket_update",
            reason=(
                f"status={ticket_status!r} is not approved, and confidence "
                f"{confidence:.2f}/severity {severity} do not meet the "
                f"auto-approve band (>={AUTO_APPROVE_CONFIDENCE}, "
                f"{sorted(AUTO_APPROVE_SEVERITIES)})"
            ),
        )
        raise ToolDenied(
            f"ticket_update denied for {ticket_id}: decision is not approved "
            f"(status={ticket_status}, confidence={confidence:.2f}, severity={severity})"
        )

    with SessionLocal() as s:
        row = s.get(TicketRow, ticket_id)
        if row is None:
            raise ToolDenied(f"ticket_update denied for {ticket_id}: ticket not found")
        external_id = (row.external_id or "").strip()

    if not external_id:
        audit.record(
            "tool.denied",
            user_id=(user or {}).get("id"),
            resource=ticket_id,
            tool="ticket_update",
            reason="missing external_id (Jira issue key)",
        )
        raise ToolDenied(
            f"ticket_update denied for {ticket_id}: missing external_id (Jira key)"
        )

    source = get_ticket_source()
    source.update(external_id, fields)
    log.info(
        "ticket_update: %s (external_id=%s) <- %s (auto_approved=%s, via %s)",
        ticket_id,
        external_id,
        fields,
        auto_approved,
        source.name,
    )
    audit.record(
        "tool.executed",
        user_id=(user or {}).get("id"),
        resource=ticket_id,
        tool="ticket_update",
        external_id=external_id,
        fields=list(fields.keys()),
        auto_approved=auto_approved,
        source=source.name,
    )
    return {
        "ticket_id": ticket_id,
        "external_id": external_id,
        "updated": list(fields.keys()),
        "auto_approved": auto_approved,
    }


# --- registry + choke point ---------------------------------------------------

TOOLS: dict[str, dict[str, Any]] = {
    "kb_search": {"fn": kb_search, "writes": False, "requires_role": None},
    "similar_tickets": {"fn": similar_tickets, "writes": False, "requires_role": None},
    "team_capacity": {"fn": team_capacity, "writes": False, "requires_role": None},
    "sla_policy": {"fn": sla_policy, "writes": False, "requires_role": None},
    "ticket_stats": {"fn": ticket_stats, "writes": False, "requires_role": "manager"},
    "rule_route": {"fn": rule_route, "writes": False, "requires_role": None},
    "ticket_update": {"fn": ticket_update, "writes": True, "requires_role": None},
}


def call(name: str, *args, user: dict | None = None, **kwargs) -> Any:
    """Every tool call in the system goes through here — never the bare function.
    Checks `requires_role` unconditionally; write-scope enforcement for
    ticket_update additionally happens inside that function itself (belt and
    braces: a role check here and an approval check there are different
    questions — "may this caller use this tool at all" vs "may this specific
    decision be written back right now")."""
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolDenied(f"no such tool: {name}")

    required_role = spec.get("requires_role")
    if required_role and (user or {}).get("role") not in (required_role, "admin"):
        audit.record(
            "tool.denied",
            user_id=(user or {}).get("id"),
            tool=name,
            reason=f"requires role {required_role!r}, caller has {(user or {}).get('role')!r}",
        )
        raise ToolDenied(f"{name} requires role {required_role!r}")

    return spec["fn"](*args, user=user, **kwargs)


_source_singleton = None


def get_ticket_source():
    """Lazy singleton so importing this module never requires Jira credentials —
    only TICKET_SOURCE=jira plus an actual write does."""
    global _source_singleton
    if _source_singleton is not None:
        return _source_singleton

    if settings.TICKET_SOURCE == "jira":
        from integrations.jira import JiraSource

        _source_singleton = JiraSource()
    else:
        from integrations.synthetic import SyntheticSource

        _source_singleton = SyntheticSource()
    return _source_singleton


def reset_ticket_source() -> None:
    """Test/demo hook — clears the cached source so switching TICKET_SOURCE at
    runtime (or retrying after fixing Jira credentials) doesn't require a
    process restart."""
    global _source_singleton
    _source_singleton = None
