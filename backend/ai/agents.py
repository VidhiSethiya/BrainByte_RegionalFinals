"""LangGraph orchestration. Two graphs live in this file, deliberately kept apart:

  1. KB chat graph  (below)   plan -> (retrieve | direct) -> generate -> verify -> END
     Powers /chat and /chatbot via chatbot.conversation_manager.handle_message().

  2. Ticket triage graph  (bottom of file)
        normalize -> enrich -> grade -> classify -> assess -> route -> reflect
        -> verify -> gate -> sync -> END
     Powers POST /tickets. See .claude/plans/BLUEPRINT.md §5 for the design and
     .claude/plans/rag-handoff.md for the RAG-layer contracts it calls into.

Both are graphs rather than straight functions for the same reason: a later stage can
route back to an earlier one exactly once. In the chat graph, `verify` retries
`retrieve` with a decomposed query when the answer came out ungrounded. In the triage
graph, `grade` (CRAG) and `reflect` (self-critique) each independently retry `enrich`
once — two separate bounded loops, not one shared budget, so a retrieval problem and a
reasoning-quality problem can each get their own fix without either starving the other.
Every loop is capped, so no path through either graph can run unboundedly.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ai.llm import chat, chat_json, chat_messages
from ai.prompts import (
    DUPLICATE_CHECK_PROMPT,
    FEATURE_EXTRACT_PROMPT,
    NO_CONTEXT_ANSWER,
    PLAN_PROMPT,
    REFLECT_PROMPT,
    ROUTE_DECIDE_PROMPT,
    SEVERITY_ASSESS_PROMPT,
    SUGGEST_FIRST_ACTION_PROMPT,
    TRIAGE_CLASSIFY_PROMPT,
    TRIAGE_POLICY_CHECK_PROMPT,
)
from chatbot.context_manager import build_messages
from config import settings
from db.sqlite.models import SessionLocal
from db.sqlite.models import Ticket as TicketRow
from db.sqlite.models import TriageRun
from guardrails.governance import audit
from guardrails.input_guard import check_input
from guardrails.output_guard import check_output
from guardrails.validators import validate_json
from observability.telemetry import Trace, log
from rag.anonymizer import anonymize_record
from rag.rag_indexer import index_ticket
from rag.rag_retriever import build_context, grade_chunks, retrieve, to_citations
from rag.schemas import (
    DuplicateVerdict,
    RAGDocument,
    ReflectionVerdict,
    RetrievedChunk,
    RoutingVerdict,
    SeverityVerdict,
    Ticket,
    TicketIngestRequest,
    TriageDecision,
    TriageVerdict,
    normalize_severity,
    sla_target_mins,
)

MAX_RETRIES = 1


class AgentState(TypedDict, total=False):
    question: str
    user: dict
    summary: str
    history: list
    filters: dict
    trace: Any

    route: str
    chunks: Annotated[list[RetrievedChunk], lambda a, b: b]
    context: str
    answer: str
    groundedness: float
    blocked: bool
    blocked_reason: str
    retries: int


# --- nodes ------------------------------------------------------------------


def plan(state: AgentState) -> AgentState:
    """Decide whether this turn needs the knowledge base at all."""
    result = chat_json(
        PLAN_PROMPT.format(question=state["question"]),
        fast=True,
        trace=state.get("trace"),
        default={},
    )
    route = (result or {}).get("route", "retrieve")
    if route not in {"retrieve", "direct", "decompose"}:
        route = "retrieve"
    return {"route": route, "retries": state.get("retries", 0)}


def retrieve_node(state: AgentState) -> AgentState:
    trace = state.get("trace")
    decompose = state.get("route") == "decompose" or state.get("retries", 0) > 0

    if trace is not None:
        with trace.stage("retrieve") as stage:
            chunks = retrieve(
                state["question"],
                user=state["user"],
                summary=state.get("summary", ""),
                filters=state.get("filters") or {},
                decompose=decompose,
                trace=trace,
            )
            stage.meta["chunks"] = len(chunks)
            stage.meta["decomposed"] = decompose
    else:
        chunks = retrieve(
            state["question"],
            user=state["user"],
            summary=state.get("summary", ""),
            filters=state.get("filters") or {},
            decompose=decompose,
        )
    return {"chunks": chunks}


def generate(state: AgentState) -> AgentState:
    chunks = state.get("chunks") or []
    if state.get("route") != "direct" and not chunks:
        return {"answer": NO_CONTEXT_ANSWER, "context": "", "groundedness": 0.0}

    messages, context = build_messages(
        state["question"],
        chunks,
        summary=state.get("summary", ""),
        history=state.get("history") or [],
    )
    trace = state.get("trace")
    if trace is not None:
        with trace.stage("generate"):
            answer = chat_messages(messages, trace=trace)
    else:
        answer = chat_messages(messages)
    return {"answer": answer, "context": context}


def verify(state: AgentState) -> AgentState:
    trace = state.get("trace")
    if trace is not None:
        with trace.stage("verify"):
            result, score = check_output(state.get("answer", ""), state.get("context", ""), trace)
    else:
        result, score = check_output(state.get("answer", ""), state.get("context", ""))

    return {
        "answer": result.text if result.allowed else "",
        "groundedness": score,
        "blocked": not result.allowed,
        "blocked_reason": result.reason,
    }


# --- edges ------------------------------------------------------------------


def route_after_plan(state: AgentState) -> str:
    return "generate" if state.get("route") == "direct" else "retrieve"


def route_after_verify(state: AgentState) -> str:
    """One retry with a decomposed query when the answer failed to ground."""
    if state.get("blocked") and state.get("retries", 0) < MAX_RETRIES and state.get("context"):
        log.info("verify failed (%s) — retrying with decomposition", state.get("blocked_reason"))
        state["retries"] = state.get("retries", 0) + 1
        return "retrieve"
    return END


def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate)
    graph.add_node("verify", verify)

    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", route_after_plan,
                                {"retrieve": "retrieve", "generate": "generate"})
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges("verify", route_after_verify, {"retrieve": "retrieve", END: END})
    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def run_turn(
    question: str,
    user: dict,
    summary: str = "",
    history: list | None = None,
    filters: dict | None = None,
    trace=None,
) -> AgentState:
    """Execute one full turn. Never raises — a failure returns a blocked state."""
    try:
        return get_graph().invoke(
            {
                "question": question,
                "user": user,
                "summary": summary,
                "history": history or [],
                "filters": filters or {},
                "trace": trace,
                "retries": 0,
            }
        )
    except Exception as exc:  # noqa: BLE001
        log.error("agent run failed: %s", exc)
        return {
            "answer": "",
            "chunks": [],
            "context": "",
            "groundedness": 0.0,
            "blocked": True,
            "blocked_reason": "The assistant could not complete this request.",
        }


# =============================================================================
# Ticket triage graph
#
#   normalize -> enrich -> grade -> classify -> assess -> route -> reflect
#   -> verify -> gate -> sync -> END
#
# Node *functions* below are prefixed `triage_` to avoid shadowing the KB chat
# graph's `plan`/`generate`/`verify` — but the graph node *keys* registered in
# _build_triage_graph() are the bare names ("normalize", "enrich", ...), because
# those exact strings are the frozen contract with the frontend's GraphNode.name
# type (frontend/FRONTEND_SPEC.md §6.1) and with docs/JUDGES_QA.md's node list.
# =============================================================================

# Each retry loop is independently capped at one. Worst case the graph visits
# enrich/grade up to 3 times (initial + one grade-rewrite + one reflect-retry) — see
# the module docstring. Every path still terminates in a bounded number of steps.
MAX_GRADE_RETRIES = 1
MAX_REFLECT_RETRIES = 1

# Below this, gate() sends the decision to a human regardless of severity.
CONFIDENCE_HUMAN_FLOOR = 0.50

# Hard floors from docs/PRIORITY_RULEBOOK.md §8.5 — force review even when the
# composite sits above CONFIDENCE_HUMAN_FLOOR. Coverage floor matches the
# human/auto-route threshold so conf ≥ 0.50 is not blocked by a stricter
# coverage-only cut.
EVIDENCE_COVERAGE_FLOOR = 0.50
BAND_MARGIN_FLOOR = 0.10

# Auto-route band: conf ≥ floor and Priority not Highest → sync writes to Jira.
# Enforced again in ai/tools.py::ticket_update (belt and braces).
AUTO_APPROVE_CONFIDENCE = 0.50
AUTO_APPROVE_SEVERITIES = {"High", "Medium", "Low"}

# How many chunks enrich asks for. Higher than the chat graph's default top_k
# because one ticket decision needs evidence from up to four doc_types in one
# retrieval — precedent tickets, a runbook, the service catalogue, the SLA policy —
# not just the single-topic answer a KB question usually needs.
TRIAGE_ENRICH_TOP_K = 8

# Priority-score decision boundaries (0–100). Used only for band_margin — the
# Priority name still comes from assess/matrix, not from these cut-points alone.
_SCORE_BOUNDARIES = (25, 50, 75)
_POLICY_DOC_TYPES = frozenset(
    {"runbook", "sla_policy", "escalation_matrix", "service_catalog", "policy"}
)


class TriageState(TypedDict, total=False):
    # input
    raw_ticket: Any  # Ticket | TicketIngestRequest | dict — see triage_normalize
    user: dict
    trace: Any

    # normalize
    ticket: Ticket
    blocked: bool
    blocked_reason: str

    # enrich / grade
    query: str
    chunks: Annotated[list[RetrievedChunk], lambda a, b: b]
    duplicate_of: str | None
    grade_action: str
    grade_rewrite_query: str | None
    grade_retries: int

    # classify
    category: str
    subcategory: str
    service: str
    classify_confidence: float
    classify_rationale: str

    # assess
    severity: str
    priority_score: int
    sla_target_mins: int
    assess_confidence: float
    assess_rationale: str

    # route
    assigned_team: str
    route_confidence: float
    route_rationale: str
    suggested_first_action: str

    # reflect
    confidence: float
    confidence_gates: dict
    confidence_limited_by: str
    reflect_issues: list[str]
    reflect_retry_enrich: bool
    reflect_rationale: str
    reflect_retries: int

    # verify
    rationale: str
    groundedness: float
    guardrails_fired: list[dict]

    # gate
    needs_human: bool
    escalation_reason: str

    # sync
    decision: TriageDecision
    status: str


# --- normalize helpers --------------------------------------------------------


def _ticket_to_doc(raw: "TicketIngestRequest | dict") -> RAGDocument:
    """Build the throwaway RAGDocument anonymize_record() expects, mirroring the
    attribute shape rag_indexer._coerce_ticket()/index_ticket() use — so a ticket
    triaged here and one indexed there produce the same masked text."""
    data = raw.model_dump() if isinstance(raw, TicketIngestRequest) else dict(raw)

    title = str(data.get("title") or "")
    body = str(data.get("body") or data.get("body_masked") or "")
    text = f"Title: {title}\n\nDescription\n{body}"

    return RAGDocument(
        id=str(data.get("id") or uuid.uuid4().hex),
        filename=f"{data.get('external_id') or 'ticket'}.txt",
        text=text,
        modality="text",
        source=f"ticket:{data.get('source') or 'manual'}",
        attributes={
            "external_id": str(data.get("external_id") or ""),
            "title": title,
            "application": str(data.get("application") or ""),
            "environment": str(data.get("environment") or "prod"),
            "channel": str(data.get("channel") or ""),
            "source": str(data.get("source") or "manual"),
            "attachments": list(data.get("attachments") or []),
            "reporter": str(data.get("reporter") or ""),
            "raw": dict(data.get("raw") or {}),
        },
    )


# --- triage nodes -------------------------------------------------------------


def triage_normalize(state: TriageState) -> TriageState:
    """PII/secret mask -> Ticket, then a defence-in-depth injection check.

    The ticket body is untrusted third-party text — anyone who can raise a ticket
    can put text in front of the model. If the caller already ran the ticket
    through rag_indexer.index_ticket() (which also anonymizes), pass the resulting
    Ticket directly and this node skips straight to the injection check instead of
    masking a second time.
    """
    trace = state.get("trace")
    raw = state["raw_ticket"]

    if isinstance(raw, Ticket):
        ticket = raw
    else:
        doc = _ticket_to_doc(raw)
        ticket = anonymize_record(doc, use_llm=True)

    combined = f"{ticket.title}\n{ticket.body_masked}"
    guard = check_input(combined, trace=trace)
    if not guard.allowed:
        log.warning("triage: ticket %s blocked at input guard (%s)", ticket.id, guard.reason)
        return {
            "ticket": ticket,
            "blocked": True,
            "blocked_reason": guard.reason,
            "guardrails_fired": [{"type": f["type"], "node": "normalize"} for f in guard.findings]
            + [{"type": "input_blocked", "node": "normalize", "reason": guard.reason}],
        }

    # Feature extraction — only for fields the caller didn't already supply, so a
    # well-formed Jira issue (application/environment already mapped) costs zero
    # extra tokens here.
    if not ticket.application or not ticket.environment:
        extracted = (
            chat_json(
                FEATURE_EXTRACT_PROMPT.format(ticket_text=combined[:3000]),
                tier="fast",
                trace=trace,
                default={},
            )
            or {}
        )
        ticket = ticket.model_copy(
            update={
                "application": ticket.application or str(extracted.get("application") or ""),
                "environment": ticket.environment or str(extracted.get("environment") or "prod"),
                "channel": ticket.channel or str(extracted.get("channel") or ""),
            }
        )

    return {"ticket": ticket, "blocked": False, "guardrails_fired": []}


def triage_enrich(state: TriageState) -> TriageState:
    """Hybrid retrieval across precedent tickets, runbooks, the service catalogue
    and the SLA policy — one call covers all four doc_types, unfiltered, because
    assess/route both need catalogue+SLA evidence that a doc_type filter would hide.
    """
    trace = state.get("trace")
    ticket = state["ticket"]
    # Prefer a CRAG rewrite when grade asked for one — must be read here, not
    # written in the router (LangGraph conditional-edge mutations do not persist).
    query = (
        state.get("grade_rewrite_query")
        or state.get("query")
        or f"{ticket.title}\n{ticket.body_masked}"[:800]
    )

    def _do_retrieve() -> list[RetrievedChunk]:
        # Over-fetch so dropping the current ticket (self-match) still leaves enough.
        return retrieve(
            query,
            user=state["user"],
            top_k=TRIAGE_ENRICH_TOP_K + 4,
            trace=trace,
        )

    if trace is not None:
        with trace.stage("enrich") as stage:
            chunks = _do_retrieve()
            stage.meta["chunks"] = len(chunks)
    else:
        chunks = _do_retrieve()

    # Never use this ticket's own indexed body as "evidence" or a duplicate of itself.
    self_key = (ticket.external_id or "").strip()
    self_id = (ticket.id or "").strip()
    chunks = [
        c
        for c in chunks
        if (c.metadata.get("external_id") or "") != self_key
        and (c.metadata.get("ticket_id") or "") != self_id
        and not (self_key and self_key in (c.filename or ""))
    ][:TRIAGE_ENRICH_TOP_K]

    # Duplicate check against the strongest precedent-ticket match, if any turned
    # up. Bounded to at most one extra fast-tier call per enrich visit.
    duplicate_of = None
    candidate = next(
        (
            c
            for c in chunks
            if c.metadata.get("doc_type") == "ticket_history"
        ),
        None,
    )
    if candidate is not None:
        verdict = validate_json(
            chat_json(
                DUPLICATE_CHECK_PROMPT.format(
                    ticket_summary=f"{ticket.title}\n{ticket.body_masked[:600]}",
                    candidate=candidate.text[:800],
                ),
                tier="fast",
                trace=trace,
                default={},
            ),
            DuplicateVerdict,  # all fields defaulted — safe without an explicit default
        )
        if verdict.is_duplicate and verdict.confidence >= 0.75:
            duplicate_of = candidate.metadata.get("external_id") or verdict.duplicate_of

    return {"query": query, "chunks": chunks, "duplicate_of": duplicate_of}


def triage_grade(state: TriageState) -> TriageState:
    """CRAG grading via the RAG layer's grade_chunks() — this graph owns the
    re-retrieve loop, RAG only grades. See rag-handoff.md §2.2."""
    trace = state.get("trace")
    result = grade_chunks(state.get("query", ""), state.get("chunks") or [], trace=trace)
    retries = int(state.get("grade_retries") or 0)
    # Budget the rewrite in this node (state updates persist). Mutating
    # grade_retries inside route_after_triage_grade does not — that caused
    # unbounded enrich↔grade loops when the grader kept asking to rewrite.
    will_retry = (
        result.action == "rewrite"
        and bool(result.rewrite_query)
        and retries < MAX_GRADE_RETRIES
    )
    return {
        "chunks": result.chunks,
        "grade_action": "rewrite" if will_retry else (
            "filter" if result.action == "rewrite" else result.action
        ),
        "grade_rewrite_query": result.rewrite_query if will_retry else "",
        "grade_retries": retries + 1 if will_retry else retries,
        "query": result.rewrite_query if will_retry else state.get("query", ""),
    }


def triage_classify(state: TriageState) -> TriageState:
    trace = state.get("trace")
    ticket = state["ticket"]
    context = build_context(state.get("chunks") or [])

    raw = chat_json(
        TRIAGE_CLASSIFY_PROMPT.format(
            ticket_text=f"{ticket.title}\n{ticket.body_masked}"[:3000],
            context=context or "(no relevant precedent retrieved)",
        ),
        tier="standard",
        trace=trace,
        default={},
    )
    verdict = validate_json(
        raw,
        TriageVerdict,
        default=TriageVerdict(category="application-error", confidence=0.0),
    )
    return {
        "category": verdict.category,
        "subcategory": verdict.subcategory,
        "service": verdict.service or ticket.application,
        "classify_confidence": verdict.confidence,
        "classify_rationale": verdict.rationale,
    }


def triage_assess(state: TriageState) -> TriageState:
    """Severity + priority. Routed to the deep model tier — this is the decision
    with the largest blast radius (a wrong Highest pages an on-call at 3am and can
    breach a contractual SLA), so it gets the strongest model in the fleet."""
    trace = state.get("trace")
    ticket = state["ticket"]
    context = build_context(state.get("chunks") or [])

    raw = chat_json(
        SEVERITY_ASSESS_PROMPT.format(
            ticket_text=f"{ticket.title}\n{ticket.body_masked}"[:3000],
            category=state.get("category", ""),
            subcategory=state.get("subcategory", ""),
            context=context or "(no SLA policy or precedent retrieved)",
        ),
        tier="deep",
        trace=trace,
        default={},
    )
    verdict = validate_json(
        raw,
        SeverityVerdict,
        default=SeverityVerdict(severity="Medium", priority_score=50, sla_target_mins=240, confidence=0.0),
    )
    return {
        "severity": verdict.severity,
        "priority_score": verdict.priority_score,
        # Looked up, not generated — see rag/schemas.py::SLA_TARGET_MINS.
        "sla_target_mins": sla_target_mins(verdict.severity),
        "assess_confidence": verdict.confidence,
        "assess_rationale": verdict.rationale,
    }


def _parse_iso_datetime(value: str):
    """Best-effort ISO-8601 parse for a ticket source's real start time (e.g.
    Jira's "created" field, "2026-08-07T22:37:41.973+0530"). Returns a naive
    UTC datetime, matching every other timestamp column in this schema
    (db/sqlite/models.py::_now) — never raises; a bad/unfamiliar format just
    means the row keeps its default creation-time value instead.
    """
    from datetime import datetime

    raw = value.strip()
    if not raw:
        return None
    try:
        # Python's fromisoformat wants "+05:30", not Jira's "+0530".
        normalized = raw
        if len(raw) >= 5 and raw[-5] in "+-" and raw[-4:].isdigit():
            normalized = f"{raw[:-2]}:{raw[-2:]}"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            from datetime import timezone

            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _rule_route(application: str) -> str:
    """Deterministic fallback so triage_route() never crashes on an unparseable
    response. Phase 2's ai/tools.py::rule_route() replaces this with a real
    service-catalogue lookup — this is the last rung of the degradation ladder
    described in BLUEPRINT.md §5, kept minimal on purpose."""
    app = (application or "").lower()
    for team in ("aws", "azure", "gcp"):
        if team in app:
            return team
    return "ops"


def _suggest_first_action(
    ticket: Ticket,
    category: str,
    subcategory: str,
    severity: str,
    trace: Any = None,
) -> str:
    """LLM-generated first troubleshooting step, from the ticket's own details
    only — deliberately given no retrieved context, so it cannot excerpt or
    cite a runbook or a prior incident. Trades away the free groundedness
    guarantee of the old excerpt-only version on purpose; see
    SUGGEST_FIRST_ACTION_PROMPT for the guardrails that keep the ask narrow."""
    ticket_text = f"{ticket.title}\n{ticket.body_masked}".strip()
    text = chat(
        SUGGEST_FIRST_ACTION_PROMPT.format(
            ticket_text=ticket_text or "(no ticket text provided)",
            application=ticket.application or "unknown",
            category=category or "unknown",
            subcategory=subcategory or "unknown",
            severity=severity or "Medium",
        ),
        tier="standard",
        trace=trace,
    )
    text = (text or "").strip()
    return text or "No recommendation available — engineer judgement required."


def triage_route(state: TriageState) -> TriageState:
    trace = state.get("trace")
    ticket = state["ticket"]
    chunks = state.get("chunks") or []
    context = build_context(chunks)
    summary = f"{ticket.title} — {state.get('category', '')}/{state.get('subcategory', '')}"

    raw = chat_json(
        ROUTE_DECIDE_PROMPT.format(
            ticket_summary=summary,
            category=state.get("category", ""),
            subcategory=state.get("subcategory", ""),
            severity=state.get("severity", "Medium"),
            context=context or "(no service catalogue retrieved)",
        ),
        tier="standard",
        trace=trace,
        default={},
    )
    verdict = validate_json(
        raw,
        RoutingVerdict,
        default=RoutingVerdict(assigned_team=_rule_route(ticket.application), confidence=0.0),
    )
    return {
        "assigned_team": verdict.assigned_team,
        "route_confidence": verdict.confidence,
        "route_rationale": verdict.rationale,
        "suggested_first_action": _suggest_first_action(
            ticket,
            state.get("category", ""),
            state.get("subcategory", ""),
            state.get("severity", "Medium"),
            trace,
        ),
    }


def _chunk_doc_type(chunk: RetrievedChunk) -> str:
    return str((chunk.metadata or {}).get("doc_type") or "").strip().lower()


def _evidence_coverage(state: TriageState) -> float:
    """Share of decision-critical evidence that was actually retrieved.

    Proxies the rulebook's evidenced÷applicable metrics using retrieval signals
    available in the graph today (policy/runbook, catalogue, precedents, fill).
    Groundedness from verify, when present, can only lower this gate.
    """
    chunks = list(state.get("chunks") or [])
    if not chunks:
        return 0.0

    types = {_chunk_doc_type(c) for c in chunks}
    signals: list[float] = []
    signals.append(1.0 if types & _POLICY_DOC_TYPES else 0.0)
    signals.append(1.0 if "service_catalog" in types else 0.0)
    signals.append(1.0 if "ticket_history" in types else 0.0)
    # Retrieval fill — empty top-k means thin context even if a type matched.
    signals.append(min(1.0, len(chunks) / max(4, TRIAGE_ENRICH_TOP_K // 2)))

    coverage = sum(signals) / len(signals)
    grounded = state.get("groundedness")
    if isinstance(grounded, (int, float)) and grounded > 0:
        coverage = min(coverage, float(grounded))
    return round(max(0.0, min(1.0, coverage)), 3)


def _band_margin(state: TriageState) -> float:
    """Normalised distance of priority_score to the nearest band boundary.

    Near a cut-point (25/50/75) the Priority name is a coin flip — margin → 0.
    Mid-band scores approach 1.0. See PRIORITY_RULEBOOK.md §8.3.
    """
    score = int(state.get("priority_score") or 50)
    score = max(0, min(100, score))
    dist = min(abs(score - b) for b in _SCORE_BOUNDARIES)
    # Half-width of a 25-point band; clamp so mid-band (12.5 away) → 1.0.
    return round(min(1.0, dist / 12.5), 3)


def _precedent_agreement(state: TriageState) -> float | None:
    """Share of retrieved ticket precedents whose Priority matches this decision.

    Returns None when no ticket_history chunks were retrieved — omitted from
    min(), not scored as zero (PRIORITY_RULEBOOK.md §8.3).
    """
    chunks = list(state.get("chunks") or [])
    precedents = [c for c in chunks if _chunk_doc_type(c) == "ticket_history"]
    if not precedents:
        return None

    decided = normalize_severity(state.get("severity")) or ""
    if not decided:
        return None

    matches = 0
    for chunk in precedents:
        meta = chunk.metadata or {}
        prior = normalize_severity(str(meta.get("severity") or meta.get("priority") or ""))
        if prior and prior == decided:
            matches += 1
    return round(matches / len(precedents), 3)


def _confidence_gates(state: TriageState) -> dict[str, float]:
    """Named gates for the composite. precedent_agreement is omitted (not
    scored as zero) when no ticket_history was retrieved — see
    _score_confidence for how these get combined."""
    gates: dict[str, float] = {
        "evidence_coverage": _evidence_coverage(state),
        "band_margin": _band_margin(state),
    }
    precedent = _precedent_agreement(state)
    if precedent is not None:
        gates["precedent_agreement"] = precedent
    return gates


def _score_confidence(state: TriageState) -> tuple[float, dict[str, float], str]:
    """Confidence = mean(evidence_coverage, precedent_agreement) — averaged
    rather than min'd, per team decision — then floored by band_margin via
    min(). band_margin stays a hard floor rather than joining the average
    because it measures something categorically different (how close the
    priority score sits to a 25/50/75 cut-point, i.e. decision clarity) from
    the other two (how much relevant evidence was actually found). Averaging
    it in would let a mid-band score compensate for a coin-flip band margin,
    which isn't the failure mode this gate exists to catch.

    Trade-off vs. the old all-three min(): a ticket with very little
    retrieved evidence but one coincidentally-matching precedent chunk can
    now score meaningfully higher than either signal alone — evidence_coverage
    and precedent_agreement are no longer independently required, they're
    compensatory. See the confidence-formula discussion in chat before
    changing this again.

    Returns (confidence, gates, limiting_gate_name). `gates` still carries the
    raw evidence_coverage/band_margin/precedent_agreement values (existing
    callers key off those names directly), plus the new
    "evidence_precedent_combined" value.
    """
    gates = _confidence_gates(state)
    if not gates:
        return 0.0, {}, "none"

    evidence = gates.get("evidence_coverage", 0.0)
    precedent = gates.get("precedent_agreement")
    band = gates.get("band_margin", 1.0)

    combined = round((evidence + precedent) / 2, 3) if precedent is not None else round(evidence, 3)
    gates = dict(gates)
    gates["evidence_precedent_combined"] = combined

    if combined <= band:
        confidence = combined
        if precedent is None:
            limiting = "evidence_coverage"
        else:
            limiting = "evidence_coverage" if evidence <= precedent else "precedent_agreement"
    else:
        confidence, limiting = band, "band_margin"

    return round(confidence, 3), gates, limiting


def _combined_confidence(state: TriageState) -> float:
    """Public entry used by reflect — weakest confidence gate, not LLM self-scores."""
    score, _, _ = _score_confidence(state)
    return score


def triage_reflect(state: TriageState) -> TriageState:
    """Self-critique against the cited evidence, not against its own prior
    reasoning — and it may only lower confidence, never raise it. Enforced here
    with min(), not just by the prompt's wording."""
    trace = state.get("trace")
    context = build_context(state.get("chunks") or [])
    base_confidence, gates, limited_by = _score_confidence(state)

    raw = chat_json(
        REFLECT_PROMPT.format(
            category=state.get("category", ""),
            subcategory=state.get("subcategory", ""),
            severity=state.get("severity", "Medium"),
            priority_score=state.get("priority_score", 50),
            assigned_team=state.get("assigned_team", "ops"),
            confidence=base_confidence,
            context=context or "(no evidence retrieved)",
        ),
        tier="deep",
        trace=trace,
        default={},
    )
    verdict = validate_json(raw, ReflectionVerdict)  # every field defaulted — safe

    final_confidence = base_confidence
    if verdict.lower_confidence_to is not None:
        final_confidence = min(base_confidence, verdict.lower_confidence_to)
        if final_confidence < base_confidence:
            limited_by = "reflect"

    retries = int(state.get("reflect_retries") or 0)
    # Same persistence rule as grade: clamp retry_enrich here. Router-only
    # increments of reflect_retries were discarded by LangGraph, so gpt-5.1
    # saying retry_enrich=true looped enrich forever → webhook/sync hung and
    # tickets landed as status=failed with "could not complete".
    will_retry = bool(verdict.retry_enrich) and retries < MAX_REFLECT_RETRIES

    return {
        "confidence": round(final_confidence, 3),
        "confidence_gates": gates,
        "confidence_limited_by": limited_by,
        "reflect_issues": verdict.issues,
        "reflect_retry_enrich": will_retry,
        "reflect_retries": retries + 1 if will_retry else retries,
        "reflect_rationale": verdict.rationale,
    }


def _compose_rationale(state: TriageState) -> str:
    """Short plain-English why — three bullets max for the decision drawer."""
    ticket = state["ticket"]
    team = state.get("assigned_team") or "ops"
    team_label = {"ops": "Ops", "azure": "Azure", "aws": "AWS", "gcp": "GCP"}.get(team, team)
    severity = state.get("severity") or "Medium"
    sla = int(state.get("sla_target_mins") or 0)
    if sla <= 0:
        sla_text = "no SLA set"
    elif sla < 60:
        sla_text = f"{sla} min"
    elif sla % 60 == 0:
        hours = sla // 60
        sla_text = f"{hours}h"
    else:
        sla_text = f"{sla / 60:.1f}h"

    category = state.get("category") or "uncategorised"
    subcategory = state.get("subcategory") or ""
    service = state.get("service") or ticket.application or "unknown service"
    kind = f"{category}" + (f" / {subcategory}" if subcategory else "")

    def _one_line(text: str, fallback: str) -> str:
        line = (text or "").strip().replace("\n", " ")
        if not line:
            return fallback
        # Keep citations; drop trailing fluff after first sentence when long.
        if len(line) > 180:
            cut = line.find(". ")
            if 40 <= cut <= 180:
                line = line[: cut + 1]
        return line

    classify_why = _one_line(state.get("classify_rationale") or "", "Matched from the ticket text.")
    assess_why = _one_line(state.get("assess_rationale") or "", "Based on impact and SLA policy.")
    route_why = _one_line(state.get("route_rationale") or "", "Based on the service catalogue.")

    parts = [
        f"- **Type:** {kind} on {service}. {classify_why}",
        f"- **Priority:** {severity} (respond in {sla_text}). {assess_why}",
        f"- **Team:** {team_label}. {route_why}",
    ]
    if state.get("duplicate_of"):
        parts.append(f"- **Note:** may duplicate {state['duplicate_of']}.")
    if state.get("reflect_issues"):
        parts.append("- **Check:** " + "; ".join(state["reflect_issues"]))
    return "\n".join(parts)


def triage_verify(state: TriageState) -> TriageState:
    """Reuses guardrails.output_guard.check_output() exactly as the KB chat graph
    does — one groundedness/policy mechanism for the whole app, not two."""
    trace = state.get("trace")
    rationale = _compose_rationale(state)
    context = build_context(state.get("chunks") or [])

    if trace is not None:
        with trace.stage("verify"):
            result, score = check_output(
                rationale, context, trace, policy_prompt=TRIAGE_POLICY_CHECK_PROMPT
            )
    else:
        result, score = check_output(
            rationale, context, policy_prompt=TRIAGE_POLICY_CHECK_PROMPT
        )

    fired = list(state.get("guardrails_fired") or [])
    if result.findings:
        fired += [{"type": f.get("type", "unknown"), "node": "verify"} for f in result.findings]

    return {
        # Kept even when blocked (unlike the chat graph) — a human reviewing a
        # gated decision needs to see *why* it was flagged, not just that it was.
        "rationale": rationale,
        "groundedness": score,
        "blocked": (not result.allowed) or state.get("blocked", False),
        "blocked_reason": result.reason if not result.allowed else state.get("blocked_reason", ""),
        "guardrails_fired": fired,
    }


def triage_gate(state: TriageState) -> TriageState:
    """Human-in-the-loop gate. Nothing here ever auto-closes or auto-remediates —
    it only decides whether a human must approve before sync() may write back.

    Confidence is recomputed here (PRIORITY_RULEBOOK.md §8) so groundedness from
    verify can still lower evidence_coverage after reflect ran.
    """
    reasons: list[str] = []
    confidence, gates, limited_by = _score_confidence(state)
    # Reflect may only have lowered the score — never raise past that floor.
    prior = state.get("confidence")
    if isinstance(prior, (int, float)) and float(prior) < confidence:
        confidence = float(prior)
        limited_by = state.get("confidence_limited_by") or "reflect"

    if state.get("blocked"):
        reasons.append(f"guardrail: {state.get('blocked_reason') or 'blocked'}")
    if state.get("severity") == "Highest":
        reasons.append("Priority Highest always requires approval")

    coverage = gates.get("evidence_coverage", 1.0)
    margin = gates.get("band_margin", 1.0)
    if coverage < EVIDENCE_COVERAGE_FLOOR:
        reasons.append(
            f"evidence coverage {coverage:.2f} below the {EVIDENCE_COVERAGE_FLOOR:.2f} floor "
            f"(less than half of the decision-critical evidence was retrieved)"
        )
    if margin < BAND_MARGIN_FLOOR:
        reasons.append(
            f"band margin {margin:.2f} below the {BAND_MARGIN_FLOOR:.2f} floor "
            f"(priority_score sits on a band boundary — coin flip)"
        )
    if confidence < CONFIDENCE_HUMAN_FLOOR:
        reasons.append(
            f"confidence {confidence:.2f} below the {CONFIDENCE_HUMAN_FLOOR:.2f} floor "
            f"(limited by {limited_by}"
            + (
                f"={gates[limited_by]:.2f}"
                if limited_by in gates
                else ""
            )
            + ")"
        )
    if state.get("duplicate_of"):
        reasons.append(f"possible duplicate of {state['duplicate_of']} — confirm before routing")

    return {
        "needs_human": bool(reasons),
        "escalation_reason": "; ".join(reasons),
        "confidence": round(confidence, 3),
        "confidence_gates": gates,
        "confidence_limited_by": limited_by,
    }


def triage_sync(state: TriageState) -> TriageState:
    """Assembles the final TriageDecision and audits it. Does NOT call Jira —
    that write path is ai/tools.py::ticket_update (Phase 2), which is also where
    the auto-approval band below is actually *enforced*, not just previewed.
    Adapter calls must receive Ticket.external_id (Jira key), never SQLite id —
    ingest_and_triage / approve_ticket resolve that before write-back."""
    trace = state.get("trace")
    ticket = state["ticket"]
    needs_human = state.get("needs_human", False)

    auto_approved = (
        not needs_human
        and state.get("confidence", 0.0) >= AUTO_APPROVE_CONFIDENCE
        and normalize_severity(state.get("severity")) in AUTO_APPROVE_SEVERITIES
    )
    status = "routed" if auto_approved else "awaiting_approval" if needs_human else "triaged"

    decision = TriageDecision(
        ticket_id=ticket.id,
        category=state.get("category", ""),
        subcategory=state.get("subcategory", ""),
        severity=state.get("severity", "Medium"),
        priority_score=state.get("priority_score", 50),
        assigned_team=state.get("assigned_team", "ops"),
        sla_target_mins=state.get("sla_target_mins", 0),
        confidence=state.get("confidence", 0.0),
        rationale=state.get("rationale", ""),
        evidence=to_citations(state.get("chunks") or [], state.get("rationale", "")),
        duplicate_of=state.get("duplicate_of"),
        suggested_first_action=state.get("suggested_first_action", ""),
        needs_human=needs_human,
        escalation_reason=state.get("escalation_reason", ""),
    )

    if trace is not None:
        stage = trace.stage("sync")
        with stage as s:
            s.meta["status"] = status
            s.meta["auto_approved"] = auto_approved

    audit.record(
        "triage.decided",
        user_id=(state.get("user") or {}).get("id"),
        resource=ticket.id,
        external_id=ticket.external_id,
        severity=decision.severity,
        assigned_team=decision.assigned_team,
        confidence=decision.confidence,
        confidence_gates=state.get("confidence_gates") or {},
        confidence_limited_by=state.get("confidence_limited_by") or "",
        needs_human=needs_human,
        auto_approved=auto_approved,
        status=status,
        guardrails_fired=len(state.get("guardrails_fired") or []),
    )

    return {"decision": decision, "status": status}


# --- triage edges ---------------------------------------------------------------


def route_after_triage_normalize(state: TriageState) -> str:
    """An injection-blocked ticket skips straight to gate — there is nothing to
    classify, but it must still land in the human queue with an audit trail, not
    vanish. See docs/JUDGES_QA.md 'the refusal beat'."""
    return "gate" if state.get("blocked") else "enrich"


def route_after_triage_grade(state: TriageState) -> str:
    # Retry budget is enforced in triage_grade (persisted state). Do not mutate
    # state here — LangGraph conditional-edge side effects are discarded.
    if state.get("grade_action") == "rewrite" and state.get("grade_rewrite_query"):
        log.info("CRAG grade requested a rewrite — retrying enrich once")
        return "enrich"
    return "classify"


def route_after_triage_reflect(state: TriageState) -> str:
    # Retry budget is enforced in triage_reflect (persisted state).
    if state.get("reflect_retry_enrich"):
        log.info("reflection flagged an evidence gap — retrying enrich once")
        return "enrich"
    return "verify"


def _build_triage_graph():
    graph = StateGraph(TriageState)
    graph.add_node("normalize", triage_normalize)
    graph.add_node("enrich", triage_enrich)
    graph.add_node("grade", triage_grade)
    graph.add_node("classify", triage_classify)
    graph.add_node("assess", triage_assess)
    graph.add_node("route", triage_route)
    graph.add_node("reflect", triage_reflect)
    graph.add_node("verify", triage_verify)
    graph.add_node("gate", triage_gate)
    graph.add_node("sync", triage_sync)

    graph.add_edge(START, "normalize")
    graph.add_conditional_edges(
        "normalize", route_after_triage_normalize, {"enrich": "enrich", "gate": "gate"}
    )
    graph.add_edge("enrich", "grade")
    graph.add_conditional_edges(
        "grade", route_after_triage_grade, {"enrich": "enrich", "classify": "classify"}
    )
    graph.add_edge("classify", "assess")
    graph.add_edge("assess", "route")
    graph.add_edge("route", "reflect")
    graph.add_conditional_edges(
        "reflect", route_after_triage_reflect, {"enrich": "enrich", "verify": "verify"}
    )
    graph.add_edge("verify", "gate")
    graph.add_edge("gate", "sync")
    graph.add_edge("sync", END)
    return graph.compile()


_triage_graph = None


def get_triage_graph():
    global _triage_graph
    if _triage_graph is None:
        _triage_graph = _build_triage_graph()
    return _triage_graph


def run_triage(
    raw_ticket: "Ticket | TicketIngestRequest | dict",
    user: dict,
    trace=None,
) -> TriageState:
    """Execute one ticket through the triage graph. Never raises — a failure
    returns a state with needs_human=True so nothing is ever silently lost; the
    ticket lands in the manager's approval queue with the exception as the
    escalation reason instead of disappearing."""
    try:
        return get_triage_graph().invoke(
            {
                "raw_ticket": raw_ticket,
                "user": user,
                "trace": trace,
                "grade_retries": 0,
                "reflect_retries": 0,
                "guardrails_fired": [],
            }
        )
    except Exception as exc:  # noqa: BLE001
        log.error("triage run failed: %s", exc)
        return {
            "blocked": True,
            "blocked_reason": "The triage agent could not complete this request.",
            "needs_human": True,
            "escalation_reason": f"triage graph exception: {exc}",
            "status": "failed",
        }


# --- shared ingest orchestration ----------------------------------------------
#
# One definition of "a ticket was triaged", called from three places that must
# never disagree on the sequence: POST /tickets (api.py), the Jira/synthetic
# poller, and POST /integrations/webhook. All three hand this function a raw
# ticket dict and get back the same (TicketRow, TriageState) pair.


def ingest_and_triage(raw_ticket: dict, user: dict) -> tuple[TicketRow, TriageState]:
    """upsert TicketRow -> run_triage() -> index_ticket() -> write the decision
    back onto TicketRow -> persist TriageRun. Matches the sequence
    .claude/plans/rag-handoff.md §2.1 documents. Never raises — a failure still
    returns a row (status="failed") and a state with needs_human=True, so a bad
    ticket lands in the manager's queue instead of vanishing from the pipeline.
    """
    with Trace("triage", user_id=(user or {}).get("id")) as trace:
        external_id = str(raw_ticket.get("external_id") or "").strip()
        source = str(raw_ticket.get("source") or "manual")

        with SessionLocal() as s:
            row = None
            if external_id:
                row = s.query(TicketRow).filter_by(source=source, external_id=external_id).first()
            if row is None:
                row = TicketRow(
                    external_id=external_id or uuid.uuid4().hex,
                    source=source,
                    title=str(raw_ticket.get("title") or ""),
                    application=str(raw_ticket.get("application") or ""),
                    environment=str(raw_ticket.get("environment") or "prod"),
                    channel=str(raw_ticket.get("channel") or ""),
                    reporter=str(raw_ticket.get("reporter") or ""),
                    assignee=str(raw_ticket.get("assignee") or ""),
                    status="new",
                )
                # SLA countdown (rag/schemas.py::sla_elapsed_fraction, Ticket.to_dict's
                # sla_due_at) has to start from when the incident actually began, not
                # from whenever our poller happened to first see it — otherwise a
                # ticket the poller was late fetching would get extra SLA time it
                # never had. Falls back to the column default (row creation time)
                # for synthetic/manual sources with no real external start time.
                created_raw = str(raw_ticket.get("created_at") or "").strip()
                if created_raw:
                    parsed_created = _parse_iso_datetime(created_raw)
                    if parsed_created:
                        row.created_at = parsed_created
                s.add(row)
            else:
                row.title = str(raw_ticket.get("title") or row.title)
                # A ticket re-fetched from the poller may have picked up a new
                # assignee since the last cycle; reporter never changes post-hoc.
                if raw_ticket.get("assignee"):
                    row.assignee = str(raw_ticket["assignee"])
            s.commit()
            s.refresh(row)
            row_id = row.id

        state = run_triage(raw_ticket, user=user, trace=trace)
        decision = state.get("decision")
        ticket = state.get("ticket")

        # Index into Chroma for future precedent search. anonymize=False because
        # triage_normalize() already masked this ticket — indexing it again with
        # anonymize=True would re-run the (slow, model-calling) anonymization pass
        # for no benefit, doubling latency and tokens on every single ticket.
        if ticket is not None:
            try:
                with trace.stage("index") as stage:
                    result = index_ticket(
                        ticket,
                        user_id=(user or {}).get("id"),
                        anonymize=False,
                        allowed_roles=(
                            [decision.assigned_team, "manager", "admin"]
                            if decision
                            else ["admin", "manager"]
                        ),
                        sensitivity="confidential",
                        category=decision.category if decision else "",
                        severity=decision.severity if decision else "",
                        team=decision.assigned_team if decision else "",
                        service=state.get("service") or ticket.application,
                    )
                    stage.meta["chunks"] = result.get("chunks", 0)
            except Exception as exc:  # noqa: BLE001
                log.error("index_ticket failed for %s: %s", ticket.id, exc)

        with SessionLocal() as s:
            row = s.get(TicketRow, row_id)
            if decision is not None:
                if ticket is not None:
                    row.body_masked = ticket.body_masked
                row.category = decision.category
                row.subcategory = decision.subcategory
                # Do not clobber a manager override on re-sync / re-triage.
                if not row.overridden_by:
                    row.severity = decision.severity
                    row.assigned_team = decision.assigned_team
                    row.priority_score = decision.priority_score
                else:
                    # Still refresh score only when priority was not the overridden field —
                    # keep both severity and team frozen once any human override exists.
                    pass
                row.confidence = decision.confidence
                row.needs_human = decision.needs_human
                row.status = state.get("status", "triaged")
                row.last_error = None
            else:
                # Dead-letter run — keep a prior human-gated decision visible in the
                # approval queue. Flipping those rows to status=failed made SCRUM
                # tickets vanish from Control Tower after a bad Sync / LLM outage.
                row.last_error = (
                    state.get("blocked_reason", "")
                    or state.get("escalation_reason", "")
                    or "triage produced no decision"
                )
                row.sync_attempts = (row.sync_attempts or 0) + 1
                if row.needs_human and row.severity and row.assigned_team:
                    row.status = "awaiting_approval"
                else:
                    row.status = state.get("status", "failed")
            s.commit()

            run = TriageRun(
                ticket_id=row.id,
                decision_json=decision.model_dump() if decision else {},
                model=settings.LLM_MODEL,
                # The ceiling tier used in this run (assess/reflect run deep);
                # TriageRun has one tier column, this graph uses three per run.
                tier="deep",
                tokens=trace.prompt_tokens + trace.completion_tokens,
                cost_usd=trace.cost_usd,
                latency_ms=trace.total_ms,
                trace_id=trace.id,
                guardrails_fired=state.get("guardrails_fired") or [],
            )
            s.add(run)
            s.commit()
            s.refresh(row)

        # Auto-approve write-back: adapter sees external_id (Jira key), never SQLite UUID.
        # ticket_update looks up the key; comment/transition use it explicitly.
        if decision is not None and state.get("status") == "routed":
            from ai.tools import ToolDenied, call as tool_call, get_ticket_source

            fields = {
                "severity": decision.severity,
                "priority_score": decision.priority_score,
                "assigned_team": decision.assigned_team,
                "confidence": decision.confidence,
            }
            try:
                tool_call(
                    "ticket_update",
                    row.id,
                    fields,
                    user=user,
                    ticket_status="routed",
                    confidence=decision.confidence,
                    severity=decision.severity,
                )
            except ToolDenied as exc:
                log.warning("auto-approve ticket_update denied for %s: %s", row.id, exc)
            else:
                external_key = (row.external_id or "").strip()
                if not external_key:
                    log.warning(
                        "auto-approve comment/transition skipped for %s: missing external_id",
                        row.id,
                    )
                else:
                    try:
                        from integrations.jira import normalize_priority

                        src = get_ticket_source()
                        pname = normalize_priority(decision.severity) or "Medium"
                        comment = (
                            f"TicketSphere auto-approved: {pname} · "
                            f"{decision.assigned_team} · "
                            f"confidence {decision.confidence:.0%}. "
                            f"{(decision.rationale or '')[:400]}"
                        )
                        if decision.suggested_first_action:
                            comment += (
                                f"\n\nRecommended resolution: "
                                f"{decision.suggested_first_action[:600]}"
                            )
                        src.add_comment(external_key, comment)
                        src.transition(external_key, "routed")
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "auto-approve comment/transition failed for %s (%s): %s",
                            row.id,
                            external_key,
                            exc,
                        )

        audit.record(
            "ticket.ingested",
            user_id=(user or {}).get("id"),
            resource=row.id,
            external_id=row.external_id,
            source=source,
            status=row.status,
            trace_id=trace.id,
        )
        return row, state


def recalculate_ticket_confidence(ticket_id: str, user: dict | None = None) -> dict[str, Any]:
    """Recompute confidence with PRIORITY_RULEBOOK §8 gates (no full re-triage).

    Re-retrieves evidence for coverage/precedent, keeps Priority/team/score from
    the ticket row (and human overrides). Updates `tickets.confidence` and the
    latest TriageRun.decision_json so Control Tower refreshes.
    """
    user = user or {
        "id": "system:confidence",
        "username": "system:confidence",
        "role": "admin",
        "clearances": ["all"],
    }
    with SessionLocal() as s:
        row = s.get(TicketRow, ticket_id)
        if row is None:
            raise ValueError(f"ticket not found: {ticket_id}")
        snapshot = {
            "id": row.id,
            "external_id": row.external_id,
            "title": row.title or "",
            "body_masked": row.body_masked or "",
            "severity": row.severity or "",
            "priority_score": int(row.priority_score or 50),
            "assigned_team": row.assigned_team or "",
            "overridden_by": row.overridden_by,
            "status": row.status,
            "needs_human": bool(row.needs_human),
        }

    query = f"{snapshot['title']}\n{snapshot['body_masked']}".strip() or snapshot["title"]
    try:
        chunks = retrieve(
            query=query[:2000],
            user=user,
            top_k=TRIAGE_ENRICH_TOP_K,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("confidence recalc retrieve failed for %s: %s", ticket_id, exc)
        chunks = []

    self_key = (snapshot["external_id"] or "").strip()
    self_id = snapshot["id"]
    chunks = [
        c
        for c in chunks
        if (c.metadata.get("external_id") or "") != self_key
        and (c.metadata.get("ticket_id") or "") != self_id
        and not (self_key and self_key in (c.filename or ""))
    ][:TRIAGE_ENRICH_TOP_K]

    state: TriageState = {
        "chunks": chunks,
        "severity": snapshot["severity"],
        "priority_score": snapshot["priority_score"],
        "assigned_team": snapshot["assigned_team"],
    }
    confidence, gates, limited_by = _score_confidence(state)

    reasons: list[str] = []
    coverage = gates.get("evidence_coverage", 1.0)
    margin = gates.get("band_margin", 1.0)
    if snapshot["severity"] == "Highest":
        reasons.append("Priority Highest always requires approval")
    if coverage < EVIDENCE_COVERAGE_FLOOR:
        reasons.append(
            f"evidence coverage {coverage:.2f} below the {EVIDENCE_COVERAGE_FLOOR:.2f} floor"
        )
    if margin < BAND_MARGIN_FLOOR:
        reasons.append(
            f"band margin {margin:.2f} below the {BAND_MARGIN_FLOOR:.2f} floor"
        )
    if confidence < CONFIDENCE_HUMAN_FLOOR:
        reasons.append(
            f"confidence {confidence:.2f} below the {CONFIDENCE_HUMAN_FLOOR:.2f} floor "
            f"(limited by {limited_by}"
            + (f"={gates[limited_by]:.2f}" if limited_by in gates else "")
            + ")"
        )
    needs_human = bool(reasons)
    escalation = "; ".join(reasons)
    sev = normalize_severity(snapshot["severity"]) or snapshot["severity"]
    auto_route = (
        not needs_human
        and confidence >= AUTO_APPROVE_CONFIDENCE
        and sev in AUTO_APPROVE_SEVERITIES
        and bool(snapshot["assigned_team"])
        and not snapshot["overridden_by"]
    )

    with SessionLocal() as s:
        row = s.get(TicketRow, ticket_id)
        row.confidence = confidence
        # Do not clobber a completed override/route — only refresh gate for open reviews.
        if row.status in ("awaiting_approval", "triaged", "failed", "new") and not row.overridden_by:
            row.needs_human = needs_human
            if needs_human and row.status in ("triaged", "new", "failed"):
                row.status = "awaiting_approval"
            elif not needs_human and row.status in ("awaiting_approval", "triaged", "new", "failed"):
                row.status = "routed" if auto_route else "triaged"
        run = (
            s.query(TriageRun)
            .filter(TriageRun.ticket_id == ticket_id)
            .order_by(TriageRun.created_at.desc())
            .first()
        )
        if run is not None:
            decision = dict(run.decision_json or {})
            decision["confidence"] = confidence
            decision["escalation_reason"] = escalation
            decision["confidence_gates"] = gates
            decision["confidence_limited_by"] = limited_by
            decision["needs_human"] = needs_human if not row.overridden_by else decision.get("needs_human", False)
            run.decision_json = decision
        s.commit()
        out = row.to_dict()
        external_key = (row.external_id or "").strip()
        routed_now = row.status == "routed" and auto_route
        fields = {
            "severity": row.severity,
            "priority_score": row.priority_score,
            "assigned_team": row.assigned_team,
            "confidence": confidence,
        }

    if routed_now:
        from ai.tools import ToolDenied, call as tool_call, get_ticket_source

        try:
            tool_call(
                "ticket_update",
                ticket_id,
                fields,
                user=user,
                ticket_status="routed",
                confidence=confidence,
                severity=sev,
            )
        except ToolDenied as exc:
            log.warning("confidence-recalc ticket_update denied for %s: %s", ticket_id, exc)
        else:
            if external_key:
                try:
                    from integrations.jira import normalize_priority

                    src = get_ticket_source()
                    pname = normalize_priority(sev) or "Medium"
                    comment = (
                        f"TicketSphere auto-routed (confidence recalc): {pname} · "
                        f"{fields.get('assigned_team')} · "
                        f"confidence {confidence:.0%}."
                    )
                    recalc_action = decision.get("suggested_first_action") if run is not None else ""
                    if recalc_action:
                        comment += f"\n\nRecommended resolution: {recalc_action[:600]}"
                    src.add_comment(external_key, comment)
                    src.transition(external_key, "routed")
                except Exception as exc:  # noqa: BLE001
                    log.warning("confidence-recalc Jira write-back failed for %s: %s", ticket_id, exc)

    out["escalation_reason"] = escalation
    out["confidence_gates"] = gates
    out["confidence_limited_by"] = limited_by
    audit.record(
        "ticket.confidence_recalculated",
        user_id=(user or {}).get("id"),
        resource=ticket_id,
        confidence=confidence,
        limited_by=limited_by,
        gates=gates,
        needs_human=needs_human,
        auto_routed=bool(routed_now),
    )
    return out


def recalculate_all_open_confidence(user: dict | None = None) -> dict[str, Any]:
    """Batch recalc for Control Tower — every non-resolved open ticket with a Priority."""
    with SessionLocal() as s:
        rows = (
            s.query(TicketRow)
            .filter(TicketRow.status.notin_(["resolved", "synced"]))
            .filter(TicketRow.severity.isnot(None))
            .filter(TicketRow.severity != "")
            .all()
        )
        ids = [r.id for r in rows]

    updated = []
    failed = []
    for tid in ids:
        try:
            updated.append(recalculate_ticket_confidence(tid, user=user))
        except Exception as exc:  # noqa: BLE001
            log.error("confidence recalc failed for %s: %s", tid, exc)
            failed.append({"ticket_id": tid, "error": str(exc)[:200]})
    return {"updated": len(updated), "failed": len(failed), "tickets": updated, "errors": failed}
