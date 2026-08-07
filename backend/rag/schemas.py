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
Environment = Literal["prod", "uat", "dev"]
TicketSource = Literal["jira", "synthetic", "manual"]

# --- priority: one vocabulary, end to end ------------------------------------
#
# P1–P4 is THE vocabulary — storage, API, and UI all speak it. There is no
# separate "severity" scale any more: the product previously carried S1–S4
# internally, "Highest/High/Medium/Low" in the UI and "P1/P2/P3" in conversation,
# and three vocabularies for one concept is how a dashboard ends up rendering
# blank tiles because two layers disagreed about what a row was called.
#
# The single exception is Jira's own Priority field, which only accepts its stock
# names. That translation happens at the adapter boundary (`to_jira_priority`)
# and nowhere else — nothing upstream of integrations/jira.py should ever see
# the word "Highest".
#
# See docs/PRIORITY_RULEBOOK.md §3 for the canonical table and how a band is
# assigned in the first place.

Priority = Literal["P1", "P2", "P3", "P4"]

#: Ordered worst-first. Index is also the rank used for sorting and for the
#: mean-absolute-error metric on the evals page.
PRIORITY_ORDER: tuple[str, ...] = ("P1", "P2", "P3", "P4")

#: Jira's stock Priority names, in the same order. Adapter boundary only.
PRIORITY_TO_JIRA: dict[str, str] = {
    "P1": "Highest",
    "P2": "High",
    "P3": "Medium",
    "P4": "Low",
}
JIRA_TO_PRIORITY: dict[str, str] = {v: k for k, v in PRIORITY_TO_JIRA.items()}

#: Retired vocabularies, accepted on input so old rows, old clients and any
#: seed data written before the rename still resolve instead of silently
#: failing a comparison. Never emitted.
_LEGACY_TO_PRIORITY: dict[str, str] = {"S1": "P1", "S2": "P2", "S3": "P3", "S4": "P4"}


def to_priority(value: str | None) -> str:
    """Normalise anything that means a priority band into P1–P4.

    Accepts the canonical form, the retired S1–S4 severity codes, and Jira's
    Highest/High/Medium/Low. Returns '' for anything unrecognised — callers
    treat that as "not set" rather than guessing a band, because guessing here
    is exactly how a P4 becomes a 3am page.
    """
    if not value:
        return ""
    raw = str(value).strip()
    upper = raw.upper()
    if upper in PRIORITY_TO_JIRA:
        return upper
    if upper in _LEGACY_TO_PRIORITY:
        return _LEGACY_TO_PRIORITY[upper]
    for jira_name, band in JIRA_TO_PRIORITY.items():
        if jira_name.lower() == raw.lower():
            return band
    return ""


def to_jira_priority(value: str | None) -> str:
    """P1–P4 -> the Jira Priority name. '' if unset or unrecognised."""
    return PRIORITY_TO_JIRA.get(to_priority(value), "")


def priority_rank(value: str | None) -> int:
    """1-based rank, worst first. 0 when unset — sorts unset rows last."""
    band = to_priority(value)
    return PRIORITY_ORDER.index(band) + 1 if band else 0


# Retired alias. Kept only so an import of `Severity` does not break at load
# time while the rename settles; it is the same P1–P4 literal, not a second
# scale. Remove once nothing imports it.
Severity = Priority


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
    severity: Priority = "P3"
    priority_score: int = Field(default=50, ge=0, le=100)
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
    """LLM JSON: severity + priority grounded in SLA / precedent."""

    severity: Severity
    priority_score: int = Field(ge=0, le=100)
    sla_target_mins: int = 0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


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
