"""PII detection, masking and redaction.

Deterministic regex only — no model call. This runs on the hot path (every inbound
message and every outbound answer) so it must be microseconds, and a guardrail that
can hallucinate is not a guardrail. The LLM pass in rag/anonymizer.py complements
this at ingest time, where latency is not a concern.

Masking is reversible-by-mapping (stable [EMAIL_1] tokens) for ordinary PII;
secrets are irreversibly replaced and never enter the token map.
Ticket ids (INC…) and error codes (ORA-, HTTP 502, KB5…) must NOT match any pattern —
hybrid retrieval depends on those exact tokens surviving.
"""

from __future__ import annotations

import re
from typing import Iterable

# Order matters: longer/more specific patterns first so they win the overlap.
PATTERNS: dict[str, re.Pattern] = {
    "AWS_KEY": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "AZURE_KEY": re.compile(
        r"(?i)(?:AccountKey|SharedAccessSignature)\s*=\s*[^\s;\"']+"
    ),
    "PRIVATE_KEY": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        r"[\s\S]*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    "CONNECTION_STRING": re.compile(
        r"(?i)(?:Password|Pwd|Secret|Api[_-]?Key|ConnectionString)\s*[:=]\s*[^\s;\"']+"
    ),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "AADHAAR": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "PAN": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    # Require a separator or +country so bare 10-digit correlation ids survive.
    "PHONE": re.compile(
        r"(?<!\d)(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s.-]){2,}\d{2,4}(?!\d)"
    ),
    "EMPLOYEE_ID": re.compile(r"\b(?:EMP|EID)[-_]?\d{4,8}\b", re.I),
    "CUSTOMER_ACCOUNT": re.compile(r"\b(?:CUST|ACCT)[-_]?\d{6,12}\b", re.I),
    # Cloud *node* hostnames only. The previous form was
    #     \b(?:ip-|ec2-|aks-|gke-)[a-z0-9.-]+\b
    # which matched any token beginning "aks-"/"gke-" — including the service
    # catalogue's own identifiers `aks-prod-01` and `gke-analytics`. Those were
    # masked to [HOSTNAME_n] at index time, so 2 of 12 catalogue entries became
    # unmatchable and no Azure AKS or GCP GKE ticket could ever retrieve its
    # owning team. Real node names always carry a pool/vmss/instance marker, a
    # dotted FQDN, or a long digit run; service identifiers do not. Requiring one
    # of those keeps genuine hostnames masked without eating the routing key.
    "HOSTNAME": re.compile(
        r"\b(?:"
        r"ip-\d{1,3}-\d{1,3}-\d{1,3}-\d{1,3}[a-z0-9.-]*"              # ip-10-0-1-23.ec2.internal
        r"|ec2-[a-z0-9.-]+"                                            # ec2-* is always an instance
        r"|(?:aks|gke)-[a-z0-9-]*(?:nodepool|node-pool|pool|vmss|instance)[a-z0-9-]*"
        r"|(?:aks|gke)-[a-z0-9-]*\d{4,}[a-z0-9-]*"                     # long numeric / hash suffix
        r"|(?:aks|gke)-[a-z0-9-]+\.[a-z0-9.-]+"                        # dotted FQDN
        r")\b",
        re.I,
    ),
    "IP": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "URL": re.compile(r"https?://[^\s<>\"]+"),
}

# Irreversible — never stored in the reverse token map.
SECRET_TYPES = {
    "AWS_KEY",
    "AZURE_KEY",
    "PRIVATE_KEY",
    "JWT",
    "CONNECTION_STRING",
}

# Patterns whose presence in an *answer* is a leak, regardless of ingest masking.
LEAK_TYPES = {
    "EMAIL",
    "CREDIT_CARD",
    "SSN",
    "AADHAAR",
    "PAN",
    "PHONE",
    "EMPLOYEE_ID",
    "CUSTOMER_ACCOUNT",
    *SECRET_TYPES,
}


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
    """Replace PII with stable typed tokens; secrets are irreversibly redacted.

    The same non-secret value always maps to the same token within one call, so
    relationships in the text survive. Secrets get a fixed [REDACTED_*] marker and
    are omitted from the reverse map.
    """
    findings = detect(text)
    if not findings:
        return text, {}

    counters: dict[str, int] = {}
    value_to_token: dict[str, str] = {}
    reverse: dict[str, str] = {}
    out, cursor = [], 0

    for finding in findings:
        value = finding["value"]
        pii_type = finding["type"]
        if pii_type in SECRET_TYPES:
            token = f"[REDACTED_{pii_type}]"
        elif value not in value_to_token:
            counters[pii_type] = counters.get(pii_type, 0) + 1
            token = f"[{pii_type}_{counters[pii_type]}]"
            value_to_token[value] = token
            reverse[token] = value
        else:
            token = value_to_token[value]

        out.append(text[cursor : finding["start"]])
        out.append(token)
        cursor = finding["end"]

    out.append(text[cursor:])
    return "".join(out), reverse


def redact_text(text: str, char: str = "█") -> str:
    """Irreversible. Used for anything that leaves the system (exports, logs)."""
    result = text
    for finding in reversed(detect(text)):
        result = result[: finding["start"]] + char * 8 + result[finding["end"] :]
    return result


def has_leak(text: str) -> list[dict]:
    """PII types that must never appear in a generated answer."""
    return detect(text, types=LEAK_TYPES)
