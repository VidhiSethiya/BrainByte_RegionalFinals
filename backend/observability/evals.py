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

from ai.llm import chat_json
from ai.prompts import CONTEXT_RELEVANCE_PROMPT, GROUNDEDNESS_PROMPT
from chatbot.conversation_manager import handle_message
from db.sqlite.models import EvalResult, SessionLocal
from guardrails.validators import validate_json
from observability.telemetry import log
from rag.rag_retriever import build_context
from rag.schemas import ChatRequest, EvalScore, GroundednessVerdict

# [PLACEHOLDER: EVAL_SET — 8-12 questions drawn from the problem statement, with a
#  `must_contain` list of facts the correct answer needs. Ship at least a few that
#  SHOULD be refused, so the guardrails are visibly exercised.]
EVAL_SET: list[dict] = [
    {"question": "[PLACEHOLDER: EVAL_QUESTION_1]", "must_contain": []},
    {"question": "[PLACEHOLDER: EVAL_QUESTION_2]", "must_contain": []},
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
    # Recall proxy: of the labels the answer cited, how many were judged relevant.
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
            # handle_message opens its own trace, so the eval loop does not nest one.
            response = handle_message(ChatRequest(message=question), user)
            score = EvalScore(
                question=question,
                answer=response.answer,
                groundedness=response.groundedness or 0.0,
                hallucination=round(1.0 - (response.groundedness or 0.0), 3),
                latency_ms=response.latency_ms,
                total_tokens=response.total_tokens,
            )
            # Citation-based precision proxy without re-running retrieval.
            score.context_precision = min(1.0, len(response.citations) / 3) if response.citations else 0.0
            score.context_recall = 1.0 if response.citations else 0.0
            scores.append(score)
        except Exception as exc:  # noqa: BLE001 - one bad case must not kill the run
            log.error("eval case failed (%s): %s", question[:50], exc)

    _persist(scores)
    return {"cases": len(scores), "summary": summarize(scores),
            "results": [s.model_dump() for s in scores]}


def summarize(scores: list[EvalScore]) -> dict:
    if not scores:
        return {"groundedness": 0.0, "context_precision": 0.0, "context_recall": 0.0,
                "hallucination_rate": 0.0, "avg_latency_ms": 0}
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
