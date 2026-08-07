"""One user message in, one persisted, guarded, audited answer out.

Pipeline:
    session -> input guard -> memory
            -> route:
                 conversational (greeting / memory-recall / ticket-SQL) via LLM
                 OR KB agent (retrieve -> generate -> verify)
            -> persist -> suggest -> audit -> telemetry

Only files in backend/chatbot/ are owned here; routes live in api.py.
"""

from __future__ import annotations

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
    # Lazy: avoids cycle agents → context_manager → chatbot → conversation_manager → agents
    from ai.agents import run_turn

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

        # 2. session memory — summary + short-term buffer (exclude turn just added)
        summary = memory.get_summary(session.id)
        history = memory.get_history(session.id)[:-1]

        # 3. route: conversational LLM vs KB agent
        greeting = context.is_greeting(question)
        memory_q = context.is_memory_question(question)
        ticket_q = context.looks_like_ticket_query(question)
        ticket_context = ""
        if ticket_q:
            with trace.stage("ticket_db") as stage:
                ticket_context = context.fetch_ticket_context(question)
                stage.meta["chars"] = len(ticket_context)

        use_conversational = greeting or memory_q or bool(ticket_context and ticket_q)

        if use_conversational:
            answer = context.conversational_reply(
                question,
                summary=summary,
                history=history,
                ticket_context=ticket_context,
                user=user,
                trace=trace,
            )
            if not answer:
                answer = (
                    "I understood you, but I could not form a reply. "
                    "Please try rephrasing."
                )
            suggestions = (
                context.greeting_suggestions()
                if greeting
                else context.suggest_followups(summary, answer, trace=trace)
            )
            message = memory.append_message(
                session.id,
                "assistant",
                answer,
                groundedness=1.0 if (greeting or memory_q or ticket_context) else None,
                latency_ms=trace.total_ms,
                prompt_tokens=trace.prompt_tokens,
                completion_tokens=trace.completion_tokens,
            )
            memory.maybe_summarize(session.id, trace=trace)
            title = context.infer_title(question, answer)
            sessions.set_title(session.id, title)
            sessions.touch(session.id)
            audit.record(
                "chat.answered",
                user_id=user["id"],
                resource=session.id,
                message_id=message.id,
                groundedness=1.0,
                citations=0,
                chunks_retrieved=0,
                conversational=True,
                greeting=greeting,
                memory_question=memory_q,
                ticket_sql=bool(ticket_context),
            )
            return ChatResponse(
                session_id=session.id,
                message_id=message.id,
                answer=answer,
                suggestions=suggestions,
                groundedness=1.0,
                latency_ms=trace.total_ms,
                total_tokens=trace.prompt_tokens + trace.completion_tokens,
                trace_id=trace.id,
            )

        # 4. KB path — rewrite follow-ups using summary + history, then agent
        with trace.stage("rewrite") as stage:
            rewritten = memory.rewrite_query(
                question, summary, history=history, trace=trace
            )
            stage.meta["rewritten"] = rewritten != question

        state = run_turn(
            rewritten,
            user=user,
            summary=summary,
            history=history,
            filters=request.filters,
            trace=trace,
        )

        # If RAG/guard blocked but we still have session memory, fall back to chat LLM
        if state.get("blocked") and history:
            with trace.stage("conversational_fallback"):
                answer = context.conversational_reply(
                    question,
                    summary=summary,
                    history=history,
                    ticket_context=ticket_context,
                    user=user,
                    trace=trace,
                )
            if answer:
                message = memory.append_message(
                    session.id,
                    "assistant",
                    answer,
                    groundedness=None,
                    latency_ms=trace.total_ms,
                    prompt_tokens=trace.prompt_tokens,
                    completion_tokens=trace.completion_tokens,
                )
                memory.maybe_summarize(session.id, trace=trace)
                sessions.set_title(session.id, context.infer_title(question, answer))
                sessions.touch(session.id)
                suggestions = context.suggest_followups(summary, answer, trace=trace)
                audit.record(
                    "chat.answered",
                    user_id=user["id"],
                    resource=session.id,
                    message_id=message.id,
                    conversational_fallback=True,
                )
                return ChatResponse(
                    session_id=session.id,
                    message_id=message.id,
                    answer=answer,
                    suggestions=suggestions,
                    latency_ms=trace.total_ms,
                    total_tokens=trace.prompt_tokens + trace.completion_tokens,
                    trace_id=trace.id,
                )

        if state.get("blocked"):
            reason = state.get("blocked_reason") or "Blocked by output guardrails."
            if reason == "The assistant could not complete this request.":
                block_code = "agent_error"
            else:
                block_code = "output_guard"
            audit.record(
                "chat.blocked_output" if block_code == "output_guard" else "chat.agent_error",
                user_id=user["id"],
                resource=session.id,
                reason=reason,
                groundedness=state.get("groundedness", 0.0),
            )
            blocked = memory.append_message(
                session.id, "assistant", reason, blocked_reason=block_code
            )
            return ChatResponse(
                session_id=session.id,
                message_id=blocked.id,
                answer=reason,
                groundedness=state.get("groundedness"),
                blocked=True,
                blocked_reason=block_code,
                latency_ms=trace.total_ms,
                trace_id=trace.id,
            )

        answer = state.get("answer", "")
        citations = to_citations(state.get("chunks") or [], answer)

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

        title = context.infer_title(question, answer)
        sessions.set_title(session.id, title)
        sessions.touch(session.id)

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
