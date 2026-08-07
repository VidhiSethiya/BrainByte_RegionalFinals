"""One user message in, one persisted, guarded, audited answer out.

This is the only orchestration entrypoint the API calls for chat. It owns the order
of the pipeline; nothing here should be reimplemented in a route handler.

    session -> rewrite -> memory -> input guard -> agent (retrieve/generate/verify)
            -> persist -> suggest -> audit -> telemetry

Two surfaces share this handler:
  - /chat     multi-session — caller supplies session_id (or a new one is created)
  - /chatbot  single-session — API pins session_id via session_manager.pinned_session
"""

from __future__ import annotations

from ai.agents import run_turn
from chatbot import context_manager as context
from chatbot import memory_manager as memory
from chatbot import session_manager as sessions
from guardrails.governance import audit
from guardrails.input_guard import check_input
from observability.telemetry import Trace
from rag.rag_retriever import to_citations
from rag.schemas import ChatRequest, ChatResponse


def handle_message(request: ChatRequest, user: dict) -> ChatResponse:
    """End-to-end chat pipeline used by both /chat and /chatbot.

    Sync (not async) so Flask routes and eval harnesses can call it directly.
    Signature and ChatResponse shape are frozen for Vidhi/Naman.
    """
    with Trace("chat", user_id=user["id"]) as trace:
        session = sessions.resolve_session(request.session_id, user["id"], request.message)

        # 1. input guardrails — before anything is persisted or retrieved
        with trace.stage("input_guard") as stage:
            guard = check_input(request.message, trace=trace)
            stage.meta["findings"] = len(guard.findings)

        if not guard.allowed:
            audit.record(
                "chat.blocked_input",
                user_id=user["id"],
                resource=session.id,
                reason=guard.reason,
                findings=guard.findings,
            )
            blocked = memory.append_message(
                session.id, "assistant", guard.reason, blocked_reason="input_guard"
            )
            return ChatResponse(
                session_id=session.id,
                message_id=blocked.id,
                answer=guard.reason,
                blocked=True,
                blocked_reason="input_guard",
                trace_id=trace.id,
            )

        question = guard.text  # PII-masked
        memory.append_message(session.id, "user", question)

        # 2. memory — summary + short-term buffer (exclude the turn just added)
        summary = memory.get_summary(session.id)
        history = memory.get_history(session.id)[:-1]

        # 3. rewrite follow-ups into a standalone retrieval query
        with trace.stage("rewrite") as stage:
            rewritten = memory.rewrite_query(question, summary, trace=trace)
            stage.meta["rewritten"] = rewritten != question

        # 4. agent (plan → retrieve → generate → verify); retrieval uses rewrite + summary
        state = run_turn(
            rewritten,
            user=user,
            summary=summary,
            history=history,
            filters=request.filters,
            trace=trace,
        )

        if state.get("blocked"):
            reason = state.get("blocked_reason") or "Blocked by output guardrails."
            audit.record(
                "chat.blocked_output",
                user_id=user["id"],
                resource=session.id,
                reason=reason,
                groundedness=state.get("groundedness", 0.0),
            )
            blocked = memory.append_message(
                session.id, "assistant", reason, blocked_reason="output_guard"
            )
            return ChatResponse(
                session_id=session.id,
                message_id=blocked.id,
                answer=reason,
                groundedness=state.get("groundedness"),
                blocked=True,
                blocked_reason="output_guard",
                latency_ms=trace.total_ms,
                trace_id=trace.id,
            )

        answer = state.get("answer", "")
        citations = to_citations(state.get("chunks") or [], answer)

        # 5. persist with per-turn telemetry attached
        message = memory.append_message(
            session.id,
            "assistant",
            answer,
            citations=[c.model_dump() for c in citations],
            groundedness=state.get("groundedness"),
            prompt_tokens=trace.prompt_tokens,
            completion_tokens=trace.completion_tokens,
            latency_ms=trace.total_ms,
        )
        memory.maybe_summarize(session.id, trace=trace)

        # 6. auto-title after the first exchange (multi-session only)
        title = context.infer_title(question, answer)
        sessions.set_title(session.id, title)
        sessions.touch(session.id)

        # 7. proactive suggestions grounded in the KB / last answer
        suggestions = context.suggest_followups(summary, answer, trace=trace)

        audit.record(
            "chat.answered",
            user_id=user["id"],
            resource=session.id,
            message_id=message.id,
            groundedness=state.get("groundedness"),
            citations=len(citations),
            chunks_retrieved=len(state.get("chunks") or []),
        )

    return ChatResponse(
        session_id=session.id,
        message_id=message.id,
        answer=answer,
        citations=citations,
        suggestions=suggestions,
        groundedness=state.get("groundedness"),
        latency_ms=trace.total_ms,
        total_tokens=trace.prompt_tokens + trace.completion_tokens,
        trace_id=trace.id,
    )
