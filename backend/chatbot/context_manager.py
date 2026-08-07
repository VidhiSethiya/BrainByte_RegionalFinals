"""Assembles what the model actually sees, under a token budget.

Priority when the budget is tight — the order is the design decision:
    system persona > current question > retrieved context > rolling summary > history

Retrieved context outranks history because an ungrounded answer is worse than a
forgetful one. Chunks are dropped from the tail (lowest rerank score) so the best
evidence always survives truncation.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ai.llm import chat_json
from ai.prompts import ANSWER_PROMPT, SUGGEST_FOLLOWUPS_PROMPT, SYSTEM_PERSONA
from config import settings
from db.sqlite.models import ChatMessage
from observability.telemetry import log
from rag.rag_retriever import build_context
from rag.schemas import RetrievedChunk

# Conservative for a 3B local model with an 8k window. Raise on build day if the
# hosted keys land a bigger model.
MAX_CONTEXT_CHARS = 6000
CHARS_PER_TOKEN = 4  # rough, but stable enough for budgeting
TITLE_CHARS = 60


def fit_chunks(chunks: list[RetrievedChunk], budget: int = MAX_CONTEXT_CHARS) -> list[RetrievedChunk]:
    """Keep the highest-ranked chunks that fit. Never splits a chunk mid-sentence."""
    kept: list[RetrievedChunk] = []
    used = 0
    for chunk in chunks:
        cost = len(chunk.text) + 60  # + label/filename header
        if used + cost > budget:
            continue
        kept.append(chunk)
        used += cost
    return kept


def build_messages(
    question: str,
    chunks: list[RetrievedChunk],
    summary: str = "",
    history: list[ChatMessage] | None = None,
) -> tuple[list, str]:
    """Returns (messages, context_string). The context string is reused by the
    output guardrail, so it must be exactly what the model saw."""
    fitted = fit_chunks(chunks)
    context = build_context(fitted) if fitted else "(no relevant documents found)"

    messages: list = [SystemMessage(content=SYSTEM_PERSONA)]

    for message in history or []:
        if message.role == "user":
            messages.append(HumanMessage(content=message.content[:1000]))
        elif message.role == "assistant" and not message.blocked_reason:
            messages.append(AIMessage(content=message.content[:1000]))

    messages.append(
        HumanMessage(
            content=ANSWER_PROMPT.format(
                context=context,
                summary=summary or "(new conversation)",
                question=question,
                domain=settings.DOMAIN,
            )
        )
    )
    return messages, context


def estimate_tokens(messages: list) -> int:
    return sum(len(str(m.content)) for m in messages) // CHARS_PER_TOKEN


def suggest_followups(summary: str, answer: str, trace=None) -> list[str]:
    """Propose up to 3 next questions grounded in the KB / last answer."""
    try:
        result = chat_json(
            SUGGEST_FOLLOWUPS_PROMPT.format(
                summary=summary or "(none)",
                answer=(answer or "")[:1200],
            ),
            fast=True,
            trace=trace,
            default={},
        )
        return [s for s in (result or {}).get("suggestions", []) if isinstance(s, str)][:3]
    except Exception as exc:  # noqa: BLE001
        log.warning("follow-up suggestions failed: %s", exc)
        return []


def infer_title(first_message: str, answer: str = "") -> str:
    """One-line session title from the first exchange (no extra LLM call).

    Uses the user question as the topic signal; falls back to a generic label.
    """
    text = (first_message or "").strip()
    if not text:
        return "New conversation"
    # Prefer the question side; strip trailing punctuation noise.
    line = text.split("\n", 1)[0].strip().rstrip("?.!")
    if len(line) > TITLE_CHARS:
        line = line[: TITLE_CHARS - 1].rstrip() + "…"
    return line or "New conversation"


def under_budget(messages: list, max_tokens: int | None = None) -> bool:
    """True when the assembled prompt fits the configured token budget."""
    budget = max_tokens or (MAX_CONTEXT_CHARS // CHARS_PER_TOKEN)
    return estimate_tokens(messages) <= budget
