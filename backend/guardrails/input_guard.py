"""Everything that happens to a user message before it reaches retrieval.

Order is deliberate — cheapest and most certain first:
  1. length / shape
  2. regex injection heuristics  (0ms, no model)
  3. PII detect -> mask          (0ms, no model)
  4. LLM injection classifier    (only if heuristics are ambiguous)

Step 4 is skipped whenever steps 2-3 already decided, which keeps the median request
free of an extra model call.
"""

from __future__ import annotations

import re

from ai.llm import chat_json
from ai.prompts import INJECTION_CHECK_PROMPT
from guardrails.pii import detect, mask_text
from guardrails.validators import validate_json
from observability.telemetry import log
from rag.schemas import GuardrailResult, InjectionVerdict

MAX_INPUT_CHARS = 4000

# High-precision injection signatures. A hit here blocks without a model call.
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.I),
    re.compile(r"disregard\s+(?:the\s+)?(?:system|above|previous)", re.I),
    re.compile(r"(?:reveal|print|show|repeat)\s+(?:me\s+)?(?:your|the)\s+(?:system\s+)?prompt", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a|an|in)\b", re.I),
    re.compile(r"\bDAN\b|\bjailbreak\b|developer\s+mode", re.I),
    re.compile(r"</?(?:system|instruction)>", re.I),
]

# Weaker signals — worth a model call, not worth a block on their own.
_SUSPICIOUS = re.compile(
    r"(?:new\s+instructions?|act\s+as|pretend\s+(?:to\s+be|you)|forget\s+everything|"
    r"base64|\\x[0-9a-f]{2}|role\s*:\s*system)",
    re.I,
)

# Escalate to the LLM classifier only when a weak signal fires. Set False to make the
# input path fully deterministic if latency becomes a problem during the demo.
LLM_CLASSIFIER_ENABLED = True


def check_input(text: str, trace=None) -> GuardrailResult:
    text = (text or "").strip()

    if not text:
        return GuardrailResult(allowed=False, reason="empty message", text="")
    if len(text) > MAX_INPUT_CHARS:
        return GuardrailResult(
            allowed=False,
            reason=f"message exceeds {MAX_INPUT_CHARS} characters",
            text="",
        )

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            log.warning("input blocked: injection pattern %s", pattern.pattern[:40])
            return GuardrailResult(
                allowed=False,
                reason="This request looks like an attempt to override system instructions.",
                text="",
                findings=[{"type": "prompt_injection", "detector": "regex"}],
            )

    findings = detect(text)
    masked, token_map = mask_text(text)
    pii_findings = [
        {"type": f["type"], "detector": "regex"} for f in findings
    ]  # values deliberately omitted so the audit log never stores raw PII

    if LLM_CLASSIFIER_ENABLED and _SUSPICIOUS.search(text):
        verdict = validate_json(
            chat_json(INJECTION_CHECK_PROMPT.format(text=masked), fast=True, trace=trace),
            InjectionVerdict,
        )
        if verdict.injection and verdict.confidence >= 0.7:
            log.warning("input blocked by classifier: %s", verdict.reason)
            return GuardrailResult(
                allowed=False,
                reason="This request looks like an attempt to override system instructions.",
                text="",
                findings=pii_findings + [{"type": "prompt_injection", "detector": "llm"}],
            )

    return GuardrailResult(
        allowed=True,
        reason="",
        # Downstream sees the masked text only. token_map stays here.
        text=masked if token_map else text,
        findings=pii_findings,
    )
