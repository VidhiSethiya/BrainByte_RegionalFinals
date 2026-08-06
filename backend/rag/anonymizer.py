"""Ingest-time de-identification.

Two passes, in this order:
  1. Deterministic regex (guardrails/pii.py) — fast, exact, never hallucinates.
  2. LLM pass — catches contextual identifiers regex cannot see (names, org names,
     free-text references).

The token map is returned, not discarded, so an authorised viewer could re-identify
later. Nothing outside this module ever sees the raw text again.
"""

from __future__ import annotations

import uuid

from ai.llm import chat, parallel_map
from ai.prompts import ANONYMIZE_PROMPT
from guardrails.pii import mask_text
from observability.telemetry import log
from rag.schemas import AnonymizedRecord, RAGDocument

# LLM anonymisation is slow on long inputs; process in windows and reassemble.
WINDOW_CHARS = 3000

# Skip the LLM pass entirely for very short inputs — regex is enough and the latency
# is not worth it. [PLACEHOLDER: tune per domain]
LLM_PASS_MIN_CHARS = 200


def anonymize_document(doc: RAGDocument, use_llm: bool = True) -> tuple[RAGDocument, dict]:
    """Return a copy of the document with PII removed, plus the token map."""
    masked, token_map = mask_text(doc.text)

    if use_llm and len(masked) >= LLM_PASS_MIN_CHARS:
        masked = _llm_pass(masked)

    scrubbed = doc.model_copy(update={"text": masked})
    return scrubbed, token_map


def anonymize_record(doc: RAGDocument, use_llm: bool = True) -> AnonymizedRecord:
    scrubbed, token_map = anonymize_document(doc, use_llm=use_llm)
    return AnonymizedRecord(
        id=doc.id or uuid.uuid4().hex,
        original_filename=doc.filename,
        text=scrubbed.text,
        tokens_replaced=token_map,
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
