"""Schema validation for LLM output.

An LLM asked for JSON returns JSON *usually*. Every parsed model output goes through
`validate_json` so a malformed response degrades to a safe default instead of raising
somewhere three layers up.
"""

from __future__ import annotations

import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from observability.telemetry import log

T = TypeVar("T", bound=BaseModel)

# Ticket-domain banned phrasings (BLUEPRINT.md §10 / .claude/plans/llm.md 3.3).
# Regex, not substring — a bare "resolved" would false-positive on a legitimate
# citation of a *resolved precedent ticket* ("[C2] was resolved by restarting
# the pod" is exactly the kind of grounded evidence a rationale should cite).
# These are anchored to a first-person claim about the CURRENT decision, never
# a fact about cited history. Secrets are deliberately not duplicated here —
# guardrails/pii.py::has_leak() + output_guard.py already redact those from
# every answer independently of this check.
_BANNED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"\bthis (ticket|issue|incident)\s+(has been|is|was)\s+(resolved|closed|fixed)\b",
            re.I,
        ),
        "claims the current ticket is resolved/closed — the system recommends, it never closes",
    ),
    (
        re.compile(r"\b(marking|mark)\s+(this\s+)?(as\s+)?(resolved|closed|done)\b", re.I),
        "claims to be marking the ticket resolved/closed — no such action exists",
    ),
    (
        re.compile(r"\bi(?:'ve| have)\s+(resolved|closed|fixed)\s+(this|it)\b", re.I),
        "claims the assistant itself resolved something — it never does",
    ),
    (
        re.compile(r"\b(will be (fixed|resolved)|eta:?)\s*(by|within|in)?\s*\d", re.I),
        "invents an ETA not sourced from the SLA policy in context",
    ),
]


def validate_json(raw: object, model: Type[T], default: T | None = None) -> T:
    """Coerce a parsed JSON blob into a Pydantic model, or fall back."""
    fallback = default if default is not None else model()
    if raw is None:
        return fallback
    if isinstance(raw, list):  # a model asked for an object sometimes returns [obj]
        raw = raw[0] if raw and isinstance(raw[0], dict) else None
    if not isinstance(raw, dict):
        return fallback
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        log.warning("%s validation failed: %s", model.__name__, exc.errors()[:2])
        return fallback


def check_response_shape(answer: str, min_chars: int = 2) -> tuple[bool, str]:
    """Cheap sanity checks on a free-text answer before it reaches the user.

    Catches the common local-model failure modes — empty output, a leaked
    prompt fragment, the model narrating its own instructions — plus the
    specific claims a TicketSphere rationale must never make: that the system
    closed something, resolved something, or promised a timeline it didn't
    read off the SLA policy.
    """
    text = (answer or "").strip()
    if len(text) < min_chars:
        return False, "empty response"

    lowered = text.lower()
    for marker in ("as an ai language model", "system prompt:", "you are an enterprise assistant"):
        if marker in lowered:
            return False, "response leaked instruction text"

    for pattern, reason in _BANNED_PATTERNS:
        if pattern.search(text):
            return False, f"banned phrasing: {reason}"

    return True, ""
