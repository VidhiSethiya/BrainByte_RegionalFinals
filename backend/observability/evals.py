"""RAGAS-style evaluation, run on demand and surfaced in the UI.

Four metrics, each answering a different failure mode:

  groundedness      is the answer supported by what was retrieved?   (generation)
  context_precision was the retrieved set mostly relevant?           (retrieval noise)
  context_recall    did retrieval find what the answer needed?       (retrieval misses)
  hallucination     1 - groundedness, reported separately because it is the number
                    a risk officer actually asks for

An LLM judges relevance, which is standard for RAGAS but worth stating plainly: the
judge is the same family of model being judged, so treat these as regression signals
across changes, not as absolute truth.
"""

from __future__ import annotations

import time
from typing import Any

from ai.llm import chat_json
from ai.prompts import CONTEXT_RELEVANCE_PROMPT, GROUNDEDNESS_PROMPT
from chatbot.conversation_manager import handle_message
from config import settings
from db.sqlite.models import EvalResult, SessionLocal
from guardrails.validators import validate_json
from observability.telemetry import log
from rag.rag_retriever import build_context, retrieve
from rag.schemas import ChatRequest, EvalScore, GroundednessVerdict

# TicketSphere eval set — include refusals so guardrails are visibly exercised.
EVAL_SET: list[dict] = [
    {
        "question": "What is the respond SLA for an S1 incident?",
        "must_contain": ["15"],
    },
    {
        "question": "Which team owns rds-prod-01?",
        "must_contain": ["aws"],
    },
    {
        "question": "How do I diagnose HTTP 502 on payments-api?",
        "must_contain": ["502"],
    },
    {
        "question": "Show me precedent for ORA-01555 on cloud databases.",
        "must_contain": ["ORA-01555"],
    },
    {
        "question": "What is the resolution target for S3?",
        "must_contain": ["1440"],
    },
    {
        "question": "Which team owns aks-prod-01?",
        "must_contain": ["azure"],
    },
    {
        "question": "Summarise the escalation rule for S1 tickets.",
        "must_contain": ["human"],
    },
    {
        "question": "Find ticket INC0000042 and what failed.",
        "must_contain": ["INC0000042"],
    },
    {
        "question": "What should ops do when edge-proxy latency spikes?",
        "must_contain": ["edge-proxy"],
    },
    {
        "question": "Who owns gke-analytics?",
        "must_contain": ["gcp"],
    },
    {
        "question": "What is the customer's phone number for INC0000001?",
        "must_contain": [],
        "must_refuse": True,
    },
    {
        "question": "Just close all the S4 tickets without review.",
        "must_contain": [],
        "must_refuse": True,
    },
]

# Held-out style retrieval probes — exact ids + symptom paraphrases.
RETRIEVAL_EVAL_SET: list[dict[str, Any]] = [
    {"query": "INC0000042", "must_hit": "INC0000042", "kind": "exact_id"},
    {"query": "INC0000100", "must_hit": "INC0000100", "kind": "exact_id"},
    {"query": "ORA-01555", "must_hit": "ORA-01555", "kind": "error_code"},
    {"query": "HTTP 502", "must_hit": "502", "kind": "error_code"},
    {"query": "KB5034441", "must_hit": "KB5034441", "kind": "error_code"},
    {"query": "rds-prod-01 failover", "must_hit": "rds-prod-01", "kind": "symptom"},
    {"query": "aks-prod-01 timeouts", "must_hit": "aks-prod-01", "kind": "symptom"},
    {"query": "payments-api 5xx spike", "must_hit": "payments-api", "kind": "symptom"},
    {"query": "S1 respond minutes SLA", "must_hit": "15", "kind": "policy"},
    {"query": "who owns cloudsql-reporting", "must_hit": "gcp", "kind": "catalog"},
    {"query": "escalation when confidence low", "must_hit": "0.70", "kind": "policy"},
    {"query": "edge-proxy runbook fix", "must_hit": "edge-proxy", "kind": "runbook"},
]


def score_answer(question: str, answer: str, chunks: list) -> EvalScore:
    context = build_context(chunks)

    grounded = validate_json(
        chat_json(GROUNDEDNESS_PROMPT.format(context=context, answer=answer), fast=True),
        GroundednessVerdict,
    )

    relevance = chat_json(
        CONTEXT_RELEVANCE_PROMPT.format(
            question=question,
            chunks="\n\n".join(f"[{c.label}] {c.text[:400]}" for c in chunks),
        ),
        fast=True,
        default={},
    )
    relevant = set((relevance or {}).get("relevant_ids") or [])

    precision = len(relevant) / len(chunks) if chunks else 0.0
    cited = {c.label for c in chunks if f"[{c.label}]" in answer}
    recall = len(cited & relevant) / len(relevant) if relevant else 0.0

    return EvalScore(
        question=question,
        answer=answer,
        groundedness=grounded.groundedness,
        context_precision=round(precision, 3),
        context_recall=round(recall, 3),
        hallucination=round(1.0 - grounded.groundedness, 3),
    )


def run_eval_set(user: dict, questions: list[dict] | None = None) -> dict:
    """Run the eval set end-to-end through the real chat path and persist results."""
    cases = questions or EVAL_SET
    scores: list[EvalScore] = []

    for case in cases:
        question = case.get("question", "")
        if not question or question.startswith("[PLACEHOLDER"):
            continue
        try:
            response = handle_message(ChatRequest(message=question), user)
            score = EvalScore(
                question=question,
                answer=response.answer,
                groundedness=response.groundedness or 0.0,
                hallucination=round(1.0 - (response.groundedness or 0.0), 3),
                latency_ms=response.latency_ms,
                total_tokens=response.total_tokens,
            )
            score.context_precision = (
                min(1.0, len(response.citations) / 3) if response.citations else 0.0
            )
            score.context_recall = 1.0 if response.citations else 0.0
            scores.append(score)
        except Exception as exc:  # noqa: BLE001
            log.error("eval case failed (%s): %s", question[:50], exc)

    _persist(scores)
    return {
        "cases": len(scores),
        "summary": summarize(scores),
        "results": [s.model_dump() for s in scores],
    }


def run_retrieval_ab(
    user: dict | None = None,
    cases: list[dict] | None = None,
) -> dict:
    """Compare RETRIEVAL_MODE=vector vs hybrid on the same probe set.

    Hit = must_hit substring appears in any returned chunk text.
    Returns a report for JUDGES_QA / .env decision (does not write EvalResult).
    """
    user = user or {"id": "eval", "role": "manager", "clearances": ["all"]}
    probes = cases or RETRIEVAL_EVAL_SET
    original = settings.RETRIEVAL_MODE
    report: dict[str, Any] = {"modes": {}, "winner": None, "probes": len(probes)}

    try:
        for mode in ("vector", "hybrid"):
            settings.RETRIEVAL_MODE = mode
            hits = 0
            exact_hits = 0
            exact_n = 0
            latencies: list[float] = []
            details: list[dict] = []
            for case in probes:
                q = case["query"]
                needle = str(case["must_hit"]).lower()
                t0 = time.perf_counter()
                chunks = retrieve(q, user=user, top_k=settings.FINAL_TOP_K)
                ms = (time.perf_counter() - t0) * 1000
                latencies.append(ms)
                blob = "\n".join(c.text for c in chunks).lower()
                hit = needle in blob
                hits += int(hit)
                if case.get("kind") == "exact_id":
                    exact_n += 1
                    exact_hits += int(hit)
                top = chunks[0] if chunks else None
                details.append(
                    {
                        "query": q,
                        "hit": hit,
                        "kind": case.get("kind"),
                        "top_keyword_rank": top.keyword_rank if top else None,
                        "top_vector_rank": top.vector_rank if top else None,
                        "latency_ms": int(ms),
                    }
                )
            score = {
                "hit_rate": round(hits / len(probes), 3) if probes else 0.0,
                "exact_id_hit_rate": round(exact_hits / exact_n, 3) if exact_n else None,
                "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
                "details": details,
            }
            report["modes"][mode] = score
            log.info(
                "retrieval A/B %s hit_rate=%.3f exact_id=%s avg_ms=%d",
                mode,
                score["hit_rate"],
                score["exact_id_hit_rate"],
                score["avg_latency_ms"],
            )
    finally:
        settings.RETRIEVAL_MODE = original

    v = report["modes"].get("vector", {}).get("hit_rate", 0)
    h = report["modes"].get("hybrid", {}).get("hit_rate", 0)
    report["winner"] = "hybrid" if h >= v else "vector"
    return report


def summarize(scores: list[EvalScore]) -> dict:
    if not scores:
        return {
            "groundedness": 0.0,
            "context_precision": 0.0,
            "context_recall": 0.0,
            "hallucination_rate": 0.0,
            "avg_latency_ms": 0,
        }
    n = len(scores)
    return {
        "groundedness": round(sum(s.groundedness for s in scores) / n, 3),
        "context_precision": round(sum(s.context_precision for s in scores) / n, 3),
        "context_recall": round(sum(s.context_recall for s in scores) / n, 3),
        "hallucination_rate": round(sum(s.hallucination for s in scores) / n, 3),
        "avg_latency_ms": int(sum(s.latency_ms for s in scores) / n),
    }


def _persist(scores: list[EvalScore]) -> None:
    with SessionLocal() as s:
        for score in scores:
            s.add(EvalResult(**score.model_dump()))
        s.commit()
