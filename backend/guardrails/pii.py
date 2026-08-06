"""PII detection, masking and redaction.

Deterministic regex only — no model call. This runs on the hot path (every inbound
message and every outbound answer) so it must be microseconds, and a guardrail that
can hallucinate is not a guardrail. The LLM pass in rag/anonymizer.py complements
this at ingest time, where latency is not a concern.

Masking is reversible-by-mapping (stable [EMAIL_1] tokens); redaction is not.
"""

from __future__ import annotations

import re
from typing import Iterable

# Order matters: longer/more specific patterns first so they win the overlap.
# [PLACEHOLDER: DOMAIN_PII_PATTERNS — add the identifiers this domain actually
#  carries, e.g. NHS number, MRN, IBAN, policy number, VIN, employee id.]
PATTERNS: dict[str, re.Pattern] = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "AADHAAR": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "PAN": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "PHONE": re.compile(r"(?<!\d)(?:\+\d{1,3}[ -]?)?(?:\d[ -]?){9,12}\d(?!\d)"),
    "IP": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "URL": re.compile(r"https?://[^\s<>\"]+"),
}

# Patterns whose presence in an *answer* is a leak, regardless of ingest masking.
LEAK_TYPES = {"EMAIL", "CREDIT_CARD", "SSN", "AADHAAR", "PAN", "PHONE"}


def detect(text: str, types: Iterable[str] | None = None) -> list[dict]:
    """Return every match as {type, value, start, end}, non-overlapping."""
    wanted = set(types) if types else set(PATTERNS)
    found: list[dict] = []
    taken: list[tuple[int, int]] = []

    for pii_type, pattern in PATTERNS.items():
        if pii_type not in wanted:
            continue
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue  # already claimed by a more specific pattern
            taken.append(span)
            found.append(
                {"type": pii_type, "value": match.group(), "start": span[0], "end": span[1]}
            )

    return sorted(found, key=lambda f: f["start"])


def mask_text(text: str) -> tuple[str, dict[str, str]]:
    """Replace PII with stable typed tokens.

    The same value always maps to the same token within one call, so relationships in
    the text survive ("[PERSON_1] emailed [PERSON_2] twice") and the result is still
    useful to embed and reason over.
    """
    findings = detect(text)
    if not findings:
        return text, {}

    counters: dict[str, int] = {}
    value_to_token: dict[str, str] = {}
    out, cursor = [], 0

    for finding in findings:
        value = finding["value"]
        if value not in value_to_token:
            counters[finding["type"]] = counters.get(finding["type"], 0) + 1
            value_to_token[value] = f"[{finding['type']}_{counters[finding['type']]}]"
        out.append(text[cursor : finding["start"]])
        out.append(value_to_token[value])
        cursor = finding["end"]

    out.append(text[cursor:])
    # token -> original, for authorised re-identification
    return "".join(out), {token: value for value, token in value_to_token.items()}


def redact_text(text: str, char: str = "█") -> str:
    """Irreversible. Used for anything that leaves the system (exports, logs)."""
    result = text
    for finding in reversed(detect(text)):
        result = result[: finding["start"]] + char * 8 + result[finding["end"] :]
    return result


def has_leak(text: str) -> list[dict]:
    """PII types that must never appear in a generated answer."""
    return detect(text, types=LEAK_TYPES)
