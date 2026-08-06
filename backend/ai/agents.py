"""LangGraph orchestration for one answer.

    plan -> (retrieve | direct) -> generate -> verify -> END

A graph rather than a straight function because `verify` can route back to `retrieve`
once: if the answer came out ungrounded, the most common cause is a bad first query,
and a single decomposed retry fixes it far more often than regenerating on the same
context. That retry edge is the whole reason this is a graph.

[PLACEHOLDER: DOMAIN_AGENTS — add specialist nodes the problem statement needs, e.g.
 a comparison node, a calculation node, a drafting node. Register them in the graph
 below and route to them from `plan`.]
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ai.llm import chat_json, chat_messages
from ai.prompts import NO_CONTEXT_ANSWER, PLAN_PROMPT
from chatbot.context_manager import build_messages
from guardrails.output_guard import check_output
from observability.telemetry import log
from rag.rag_retriever import retrieve
from rag.schemas import RetrievedChunk

MAX_RETRIES = 1


class AgentState(TypedDict, total=False):
    question: str
    user: dict
    summary: str
    history: list
    filters: dict
    trace: Any

    route: str
    chunks: Annotated[list[RetrievedChunk], lambda a, b: b]
    context: str
    answer: str
    groundedness: float
    blocked: bool
    blocked_reason: str
    retries: int


# --- nodes ------------------------------------------------------------------


def plan(state: AgentState) -> AgentState:
    """Decide whether this turn needs the knowledge base at all."""
    result = chat_json(
        PLAN_PROMPT.format(question=state["question"]),
        fast=True,
        trace=state.get("trace"),
        default={},
    )
    route = (result or {}).get("route", "retrieve")
    if route not in {"retrieve", "direct", "decompose"}:
        route = "retrieve"
    return {"route": route, "retries": state.get("retries", 0)}


def retrieve_node(state: AgentState) -> AgentState:
    trace = state.get("trace")
    decompose = state.get("route") == "decompose" or state.get("retries", 0) > 0

    if trace is not None:
        with trace.stage("retrieve") as stage:
            chunks = retrieve(
                state["question"],
                user=state["user"],
                summary=state.get("summary", ""),
                filters=state.get("filters") or {},
                decompose=decompose,
                trace=trace,
            )
            stage.meta["chunks"] = len(chunks)
            stage.meta["decomposed"] = decompose
    else:
        chunks = retrieve(
            state["question"],
            user=state["user"],
            summary=state.get("summary", ""),
            filters=state.get("filters") or {},
            decompose=decompose,
        )
    return {"chunks": chunks}


def generate(state: AgentState) -> AgentState:
    chunks = state.get("chunks") or []
    if state.get("route") != "direct" and not chunks:
        return {"answer": NO_CONTEXT_ANSWER, "context": "", "groundedness": 0.0}

    messages, context = build_messages(
        state["question"],
        chunks,
        summary=state.get("summary", ""),
        history=state.get("history") or [],
    )
    trace = state.get("trace")
    if trace is not None:
        with trace.stage("generate"):
            answer = chat_messages(messages, trace=trace)
    else:
        answer = chat_messages(messages)
    return {"answer": answer, "context": context}


def verify(state: AgentState) -> AgentState:
    trace = state.get("trace")
    if trace is not None:
        with trace.stage("verify"):
            result, score = check_output(state.get("answer", ""), state.get("context", ""), trace)
    else:
        result, score = check_output(state.get("answer", ""), state.get("context", ""))

    return {
        "answer": result.text if result.allowed else "",
        "groundedness": score,
        "blocked": not result.allowed,
        "blocked_reason": result.reason,
    }


# --- edges ------------------------------------------------------------------


def route_after_plan(state: AgentState) -> str:
    return "generate" if state.get("route") == "direct" else "retrieve"


def route_after_verify(state: AgentState) -> str:
    """One retry with a decomposed query when the answer failed to ground."""
    if state.get("blocked") and state.get("retries", 0) < MAX_RETRIES and state.get("context"):
        log.info("verify failed (%s) — retrying with decomposition", state.get("blocked_reason"))
        state["retries"] = state.get("retries", 0) + 1
        return "retrieve"
    return END


def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate)
    graph.add_node("verify", verify)

    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", route_after_plan,
                                {"retrieve": "retrieve", "generate": "generate"})
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges("verify", route_after_verify, {"retrieve": "retrieve", END: END})
    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def run_turn(
    question: str,
    user: dict,
    summary: str = "",
    history: list | None = None,
    filters: dict | None = None,
    trace=None,
) -> AgentState:
    """Execute one full turn. Never raises — a failure returns a blocked state."""
    try:
        return get_graph().invoke(
            {
                "question": question,
                "user": user,
                "summary": summary,
                "history": history or [],
                "filters": filters or {},
                "trace": trace,
                "retries": 0,
            }
        )
    except Exception as exc:  # noqa: BLE001
        log.error("agent run failed: %s", exc)
        return {
            "answer": "",
            "chunks": [],
            "context": "",
            "groundedness": 0.0,
            "blocked": True,
            "blocked_reason": "The assistant could not complete this request.",
        }
