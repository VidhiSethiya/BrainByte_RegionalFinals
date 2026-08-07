"""Every request/response/LLM-output shape in the system.

Defined once here and imported everywhere. Do not redeclare a shape in a route.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# --- auth -------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


# --- ingestion / documents --------------------------------------------------

DocType = Literal[
    "ticket_history",
    "runbook",
    "service_catalog",
    "sla_policy",
    "escalation_matrix",
]
Team = Literal["ops", "azure", "aws", "gcp"]
# Same vocabulary as Jira native Priority (stock Software board groups).
Severity = Literal["Highest", "High", "Medium", "Low"]
Environment = Literal["prod", "uat", "dev"]
TicketSource = Literal["jira", "synthetic", "manual"]

# Two retired vocabularies, both accepted on input so an un-migrated row, a
# bookmarked URL or someone typing the shorthand a reviewer uses still resolves
# instead of silently matching nothing. Never emitted — output is always the
# Jira Priority name.
_LEGACY_SEVERITY = {
    "S1": "Highest", "S2": "High", "S3": "Medium", "S4": "Low",
    "P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low",
}
_PRIORITY_NAMES = frozenset({"Highest", "High", "Medium", "Low"})


#: Response/resolution targets per band, in minutes. MUST stay in step with
#: db/vectordb/data/seed/sla_policy.md — that document is what a reviewer sees,
#: this table is what the code applies. An SLA figure is a lookup, not a
#: judgement: asking the model for it produced a fabricated "60 minutes" that the
#: policy guard then (correctly) flagged as invented evidence. Same principle as
#: ticket_stats — the LLM never supplies a number that a table can answer.
SLA_TARGET_MINS: dict[str, dict[str, int]] = {
    "Highest": {"respond": 15, "resolve": 240},
    "High": {"respond": 30, "resolve": 480},
    "Medium": {"respond": 120, "resolve": 1440},
    "Low": {"respond": 480, "resolve": 4320},
}


def sla_target_mins(priority: str | None, kind: str = "resolve") -> int:
    """Resolution (default) or response target for a band. 0 when unset."""
    return SLA_TARGET_MINS.get(normalize_severity(priority), {}).get(kind, 0)


def normalize_severity(value: str | None) -> str:
    """Map legacy S1–S4 / P1–P4 (and case variants) onto Jira Priority names."""
    if not value:
        return ""
    raw = str(value).strip()
    if raw in _PRIORITY_NAMES:
        return raw
    upper = raw.upper()
    if upper in _LEGACY_SEVERITY:
        return _LEGACY_SEVERITY[upper]
    # Case-insensitive match for Highest/High/Medium/Low
    for name in _PRIORITY_NAMES:
        if name.lower() == raw.lower():
            return name
    return raw


class RAGDocument(BaseModel):
    """A source document before chunking."""

    id: str | None = None
    filename: str
    text: str
    modality: Literal["text", "pdf", "image"] = "text"
    source: str | None = None
    # Governance metadata — enforced at query time, not after retrieval.
    allowed_roles: list[str] = Field(default_factory=lambda: ["admin"])
    sensitivity: Literal["public", "internal", "confidential", "restricted"] = "internal"
    # Filterable Chroma attributes (TicketSphere): doc_type, team, service,
    # environment, category, severity, resolved, resolution_minutes.
    attributes: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    id: str
    doc_id: str
    text: str
    ordinal: int
    page: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    """A chunk after fusion + reranking, ready for the prompt."""

    id: str
    doc_id: str
    filename: str
    text: str
    page: int | None = None
    score: float = 0.0
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def label(self) -> str:
        """Citation label used in prompts and returned to the UI."""
        return self.metadata.get("label", self.id)


class Citation(BaseModel):
    label: str
    doc_id: str
    filename: str
    page: int | None = None
    snippet: str


# --- chat -------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    # Optional metadata filter from the UI, e.g. {"sensitivity": "internal"}
    filters: dict[str, str] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be blank")
        return v.strip()


class ChatResponse(BaseModel):
    session_id: str
    message_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    groundedness: float | None = None
    blocked: bool = False
    blocked_reason: str | None = None
    latency_ms: int = 0
    total_tokens: int = 0
    trace_id: str = ""
    # Populated only for role=="admin" on a ticket-SQL answer (e.g. "get me all P1
    # issues") when at least one matched ticket still needs approval — the ids the
    # chat's admin-only "Bulk approve & route" button sends to
    # POST /tickets/bulk-approve. Never populated for any other role: the LLM only
    # ever lists candidates, it never approves anything itself (see
    # chatbot/context_manager.py::fetch_approvable_tickets and
    # api.py::bulk_approve_tickets).
    actionable_ticket_ids: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    message_id: str
    rating: Literal[-1, 1]
    comment: str = ""
    corrected_answer: str | None = None


# --- guardrail outputs (LLM JSON, validated before use) ----------------------


class InjectionVerdict(BaseModel):
    injection: bool = False
    confidence: float = 0.0
    reason: str = ""


class PolicyVerdict(BaseModel):
    violation: bool = False
    policy: str = ""
    reason: str = ""


class GroundednessVerdict(BaseModel):
    groundedness: float = 0.0
    unsupported_claims: list[str] = Field(default_factory=list)


class GuardrailResult(BaseModel):
    """Uniform verdict returned by every guard."""

    allowed: bool = True
    reason: str = ""
    text: str = ""  # possibly masked/redacted text to use downstream
    findings: list[dict[str, Any]] = Field(default_factory=list)


# --- domain artifacts (TicketSphere) ----------------------------------------


class Ticket(BaseModel):
    """Ticket after PII/secret scrubbing — what gets embedded / triaged."""

    id: str
    external_id: str = ""
    source: TicketSource = "manual"
    title: str = ""
    body_masked: str = ""
    reporter_token: str = ""
    application: str = ""
    environment: Environment | str = "prod"
    channel: str = ""
    attachments: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    tokens_replaced: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | None = None


# Backward-compatible alias for ingest helpers that still say "anonymized record".
AnonymizedRecord = Ticket


class TriageDecision(BaseModel):
    """Structured triage output the agent graph produces for a ticket."""

    ticket_id: str
    category: str = ""
    subcategory: str = ""
    severity: Severity = "Medium"
    priority_score: int = Field(default=50, ge=0, le=100)

    @field_validator("severity", mode="before")
    @classmethod
    def _norm_severity(cls, v: object) -> object:
        if v is None or v == "":
            return "Medium"
        return normalize_severity(str(v)) or "Medium"
    assigned_team: Team = "ops"
    sla_target_mins: int = 0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    evidence: list[Citation] = Field(default_factory=list)
    duplicate_of: str | None = None
    suggested_first_action: str = ""
    needs_human: bool = False
    escalation_reason: str = ""


# Backward-compatible alias.
GeneratedReport = TriageDecision


class TicketIngestRequest(BaseModel):
    """Inbound ticket payload before normalisation / triage."""

    external_id: str | None = None
    source: TicketSource = "manual"
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50_000)
    application: str = ""
    environment: Environment | str = "prod"
    channel: str = "api"
    attachments: list[str] = Field(default_factory=list)
    reporter: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class BulkApproveRequest(BaseModel):
    """Admin-only bulk version of the single-ticket approve gate. Capped at 50 —
    this is a chat-driven convenience action on a handful of listed tickets, not
    a mass-migration tool."""

    ticket_ids: list[str] = Field(min_length=1, max_length=50)


class OverrideRequest(BaseModel):
    """Manager/engineer override — reason is mandatory."""

    field: Literal["severity", "assigned_team", "category", "priority_score", "status"]
    new_value: str | int
    reason: str = Field(min_length=3, max_length=2000)


class TriageVerdict(BaseModel):
    """LLM JSON: category + subcategory + affected service."""

    category: str
    subcategory: str = ""
    service: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class SeverityVerdict(BaseModel):
    """LLM JSON: Priority (Jira names) grounded in SLA / precedent."""

    severity: Severity
    priority_score: int = Field(ge=0, le=100)
    sla_target_mins: int = 0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def _norm_severity(cls, v: object) -> object:
        if v is None or v == "":
            return "Medium"
        return normalize_severity(str(v)) or "Medium"


class RoutingVerdict(BaseModel):
    """LLM JSON: owning team from catalogue ⊕ capacity."""

    assigned_team: Team
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class DuplicateVerdict(BaseModel):
    """LLM JSON: whether this ticket duplicates an open/resolved one."""

    is_duplicate: bool = False
    duplicate_of: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class TicketStats(BaseModel):
    """Deterministic SQL aggregate — narrated by the manager chatbot, never invented."""

    total: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_team: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    sla_at_risk: int = 0
    awaiting_approval: int = 0
    from_date: str | None = None
    to_date: str | None = None


class ReflectionVerdict(BaseModel):
    """Self-critique of an assembled TriageDecision against cited evidence."""

    pass_check: bool = True
    lower_confidence_to: float | None = None
    issues: list[str] = Field(default_factory=list)
    retry_enrich: bool = False
    rationale: str = ""


class ChunkGradeVerdict(BaseModel):
    """CRAG grader JSON — keep / drop / ask for rewrite+re-retrieve."""

    action: Literal["keep", "filter", "rewrite"] = "keep"
    keep_labels: list[str] = Field(default_factory=list)
    rewrite_query: str | None = None
    reason: str = ""


class GradeResult(BaseModel):
    """Return shape of `grade_chunks` for the agents team's CRAG node."""

    chunks: list[RetrievedChunk] = Field(default_factory=list)
    action: Literal["keep", "filter", "rewrite", "none"] = "keep"
    rewrite_query: str | None = None
    reason: str = ""


# --- evals ------------------------------------------------------------------


class EvalScore(BaseModel):
    question: str
    answer: str = ""
    groundedness: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0
    hallucination: float = 0.0
    latency_ms: int = 0
    total_tokens: int = 0
