"""Assembles what the model actually sees, under a token budget.

Priority when the budget is tight — the order is the design decision:
    system persona > current question > retrieved context > rolling summary > history

Retrieved context outranks history because an ungrounded answer is worse than a
forgetful one. Chunks are dropped from the tail (lowest rerank score) so the best
evidence always survives truncation.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ai.prompts import ANSWER_PROMPT, SYSTEM_PERSONA
from config import settings
from db.sqlite.models import ChatMessage
from rag.rag_retriever import build_context
from rag.schemas import RetrievedChunk

# Conservative for a 3B local model with an 8k window. Raise on build day if the
# hosted keys land a bigger model. [PLACEHOLDER: tune to the deployed context window]
MAX_CONTEXT_CHARS = 6000
CHARS_PER_TOKEN = 4  # rough, but stable enough for budgeting


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
