"""Ingest-time de-identification.

Two passes, in this order:
  1. Irreversible secret wipe (AWS keys, PEMs, JWTs, connection strings) — never
     stored in the token map.
  2. Deterministic regex (guardrails/pii.py) — fast, exact, never hallucinates.
  3. LLM pass — catches contextual identifiers regex cannot see (names, org names,
     free-text references). Skipped for short ticket bodies.

The token map is returned, not discarded, so an authorised viewer could re-identify
later. Nothing outside this module ever sees the raw text again.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from ai.llm import chat, parallel_map
from ai.prompts import ANONYMIZE_PROMPT
from guardrails.pii import mask_text
from observability.telemetry import log
from rag.schemas import RAGDocument, Ticket

# LLM anonymisation is slow on long inputs; process in windows and reassemble.
WINDOW_CHARS = 3000

# Tickets are short and noisy — regex (+ secret wipe) is enough below this length.
LLM_PASS_MIN_CHARS = 120

# Secrets are redacted irreversibly (not token-mapped). Keep patterns here so the
# rag layer can protect ticket bodies even before domain PII patterns land in pii.py.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)(AccountKey|SharedAccessSignature)\s*=\s*[^\s;\"']+"), r"\1=[REDACTED]"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)(Password|Pwd|Secret|Api[_-]?Key|ConnectionString)\s*[:=]\s*[^\s;\"']+"), r"\1=[REDACTED]"),
]


def _redact_secrets(text: str) -> str:
    """Irreversible secret scrub — replacements are never put in tokens_replaced."""
    out = text
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def anonymize_document(doc: RAGDocument, use_llm: bool = True) -> tuple[RAGDocument, dict]:
    """Return a copy of the document with PII removed, plus the token map."""
    scrubbed = _redact_secrets(doc.text)
    masked, token_map = mask_text(scrubbed)

    if use_llm and len(masked) >= LLM_PASS_MIN_CHARS:
        # Ticket bodies must keep INC… / error codes for hybrid BM25. Local/mini models
        # often rewrite those into TOKEN_N and destroy lexical match — regex+secrets is enough.
        if (doc.attributes or {}).get("doc_type") != "ticket_history":
            masked = _llm_pass(masked)

    return doc.model_copy(update={"text": masked}), token_map


def anonymize_record(doc: RAGDocument, use_llm: bool = True) -> Ticket:
    """Produce a domain Ticket from a RAGDocument after de-identification."""
    scrubbed, token_map = anonymize_document(doc, use_llm=use_llm)
    attrs = doc.attributes or {}

    reporter = str(attrs.get("reporter") or attrs.get("reporter_token") or "")
    reporter_token = ""
    if reporter:
        for token, original in token_map.items():
            if original == reporter:
                reporter_token = token
                break
        if not reporter_token:
            reporter_token = reporter if reporter.startswith("[") else "[REPORTER]"

    env = attrs.get("environment") or "prod"
    source = attrs.get("source") or "manual"
    if source not in ("jira", "synthetic", "manual"):
        source = "manual"

    return Ticket(
        id=doc.id or uuid.uuid4().hex,
        external_id=str(attrs.get("external_id") or ""),
        source=source,  # type: ignore[arg-type]
        title=str(attrs.get("title") or doc.filename),
        body_masked=scrubbed.text,
        reporter_token=reporter_token,
        application=str(attrs.get("application") or attrs.get("service") or ""),
        environment=env,  # type: ignore[arg-type]
        channel=str(attrs.get("channel") or ""),
        attachments=(
            list(attrs.get("attachments") or [])
            if isinstance(attrs.get("attachments"), list)
            else [a for a in str(attrs.get("attachments") or "").split(",") if a]
        ),
        raw=dict(attrs.get("raw") or {}) if isinstance(attrs.get("raw"), dict) else {},
        tokens_replaced=token_map,
        created_at=datetime.now(timezone.utc),
    )


def _llm_pass(text: str) -> str:
    windows = [text[i : i + WINDOW_CHARS] for i in range(0, len(text), WINDOW_CHARS)]
    results = parallel_map(
        lambda w: chat(ANONYMIZE_PROMPT.format(text=w), fast=True, temperature=0),
        windows,
        seconds=120,
    )
    out = []
    for window, result in zip(windows, results):
        if result:
            out.append(result)
        else:
            # Failing open would leak PII, so keep the regex-masked window instead.
            log.warning("LLM anonymisation window failed — keeping regex-masked text")
            out.append(window)
    return "\n".join(out)
