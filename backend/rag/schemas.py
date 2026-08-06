"""Every request/response/LLM-output shape in the system.

Defined once here and imported everywhere. Do not redeclare a shape in a route.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# --- auth -------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)


# --- ingestion / documents --------------------------------------------------


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
    # [PLACEHOLDER: DOMAIN_DOCUMENT_ATTRIBUTES]
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


# --- domain artifacts -------------------------------------------------------
# [PLACEHOLDER: rename these two to the actual entities in the problem statement.
#  They exist so the ingest -> anonymize -> structure -> index pipeline has a
#  concrete typed output rather than passing dicts around.]


class AnonymizedRecord(BaseModel):
    """Raw input after PII removal — what actually gets embedded."""

    id: str
    original_filename: str
    text: str
    tokens_replaced: dict[str, str] = Field(default_factory=dict)
    # [PLACEHOLDER: DOMAIN_RECORD_FIELDS]


class GeneratedReport(BaseModel):
    """Structured artifact the system produces for the user."""

    id: str
    title: str
    summary: str
    findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    # [PLACEHOLDER: DOMAIN_REPORT_FIELDS e.g. severity, risk_score, owner]


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
