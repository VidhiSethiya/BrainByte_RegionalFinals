"""The only place a model client is constructed, plus the concurrency primitives
every model call goes through.

Both chat and embeddings speak the OpenAI wire protocol via `langchain_openai`, so the
same code path serves local Ollama and a hosted endpoint. Switching is an env change.

Provider resolution runs once at boot:
  LLM_PROVIDER=hosted + a working key -> hosted
  anything else, or a failed probe    -> local Ollama
"""

from __future__ import annotations

import json
import re
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from functools import lru_cache
from typing import Any, Callable, Iterable, Literal, TypeVar

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from config import settings
from observability.telemetry import log

T = TypeVar("T")
R = TypeVar("R")

# Three tiers, not one model. Which tier a call gets is a cost/quality decision made
# at the call site, not a global setting — see docs/JUDGES_QA.md "Which model are
# you using?" for the reasoning.
#   deep     -> settings.REASONING_MODEL  — severity/priority, reflection, manager
#               Q&A: the calls where a wrong answer is expensive. ~15% of calls.
#   standard -> settings.LLM_MODEL        — generation, classification, routing.
#   fast     -> settings.FAST_LLM_MODEL   — plan, rewrite, CRAG grading, guardrail
#               JSON, summaries. ~70% of calls, short and schema-bound.
ModelTier = Literal["fast", "standard", "deep"]

# Two pools, deliberately. `parallel_map` fans out work whose individual items each
# call `with_timeout` — sharing one pool would let the fan-out saturate every worker
# while each task waits for an inner worker that can never start. Classic deadlock.
_FANOUT_POOL = ThreadPoolExecutor(
    max_workers=settings.MAX_PARALLEL_WORKERS, thread_name_prefix="fanout"
)
_CALL_POOL = ThreadPoolExecutor(
    max_workers=settings.MAX_PARALLEL_WORKERS * 4, thread_name_prefix="call"
)

_provider: dict[str, Any] | None = None


class TimeoutExceeded(RuntimeError):
    pass


# --- concurrency ------------------------------------------------------------


def with_timeout(fn: Callable[..., R], *args, seconds: int | None = None, **kwargs) -> R:
    """Run a blocking call under a hard wall-clock cap.

    Every LLM / embedding / external call goes through this. A hung Ollama must not
    hang the request.
    """
    limit = seconds or settings.LLM_TIMEOUT_SECONDS
    future = _CALL_POOL.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=limit)
    except FuturesTimeout as exc:
        future.cancel()
        raise TimeoutExceeded(f"call exceeded {limit}s") from exc


def parallel_map(fn: Callable[[T], R], items: Iterable[T], seconds: int | None = None) -> list[Any]:
    """Bounded fan-out. Preserves input order; failures come back as None.

    Used for: embedding batches, multi-query retrieval, parallel guardrail checks.
    """
    items = list(items)
    if not items:
        return []
    limit = seconds or settings.LLM_TIMEOUT_SECONDS
    futures = [_FANOUT_POOL.submit(fn, item) for item in items]
    results: list[Any] = []
    for future in futures:
        try:
            results.append(future.result(timeout=limit))
        except Exception:  # noqa: BLE001 - one bad item must not kill the batch
            results.append(None)
    return results


# --- clients ----------------------------------------------------------------


@lru_cache(maxsize=1)
def _http_client() -> httpx.Client | None:
    """Shared httpx client with TLS verification disabled when configured.

    Ollama is plain http locally, but a hosted endpoint behind a TLS-inspecting
    corporate proxy fails certificate validation — which surfaces as an SSL error
    mid-demo. Returning None lets the SDK build its own verified client.
    """
    if not settings.DISABLE_SSL_VERIFY:
        return None
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")
    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:  # noqa: BLE001 - urllib3 is transitive, not required
        pass
    log.warning("TLS verification disabled (DISABLE_SSL_VERIFY=true)")
    return httpx.Client(verify=False, timeout=settings.LLM_TIMEOUT_SECONDS)


def _client_kwargs(base_url: str, api_key: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"base_url": base_url, "api_key": api_key}
    client = _http_client()
    if client is not None:
        kwargs["http_client"] = client
    return kwargs


def resolve_provider() -> dict[str, Any]:
    """Pick hosted vs local once, probing the hosted endpoint before trusting it."""
    global _provider
    if _provider is not None:
        return _provider

    local = {
        "name": "local",
        "base_url": settings.LOCAL_BASE_URL,
        "api_key": settings.LOCAL_API_KEY,
    }

    if settings.LLM_PROVIDER != "hosted":
        _provider = local
        return _provider

    hosted = {
        "name": "hosted",
        "base_url": settings.OPENAI_BASE_URL,
        "api_key": settings.OPENAI_API_KEY,
    }
    try:
        probe = ChatOpenAI(
            model=settings.FAST_LLM_MODEL,
            temperature=0,
            max_retries=0,
            timeout=10,
            **_client_kwargs(hosted["base_url"], hosted["api_key"]),
        )
        with_timeout(probe.invoke, [HumanMessage(content="ping")], seconds=12)
        _provider = hosted
    except Exception as exc:  # noqa: BLE001 - any failure means fall back, not crash
        log.warning("hosted provider probe failed (%s) -> falling back to local Ollama", exc)
        _provider = local
    return _provider


@lru_cache(maxsize=8)
def get_llm(
    tier: ModelTier | None = None,
    fast: bool = False,
    temperature: float | None = None,
) -> ChatOpenAI:
    """Return a client for one of three tiers.

    `fast=True` is a deprecated alias for `tier="fast"`, kept so existing call
    sites (guardrails, evals, rag_retriever, chatbot) do not need to change in the
    same breath as this signature. When both are given, `tier` wins.
    """
    resolved: ModelTier = tier or ("fast" if fast else "standard")
    p = resolve_provider()

    if p["name"] == "local":
        # The three tiers collapse to whichever one chat model Ollama actually has
        # pulled. The hosted-only ids in settings (azure/genailab-maas-...) do not
        # exist on a local Ollama daemon and would 404 — this is what actually
        # makes "falls back to local automatically" (docs/JUDGES_QA.md) true
        # instead of aspirational when the hosted probe fails mid-session.
        model = settings.LOCAL_CHAT_MODEL
    else:
        model = {
            "fast": settings.FAST_LLM_MODEL,
            "standard": settings.LLM_MODEL,
            "deep": settings.REASONING_MODEL,
        }[resolved]

    return ChatOpenAI(
        model=model,
        temperature=settings.LLM_TEMPERATURE if temperature is None else temperature,
        max_retries=settings.LLM_MAX_RETRIES,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        **_client_kwargs(p["base_url"], p["api_key"]),
    )


@lru_cache(maxsize=1)
def get_embeddings() -> OpenAIEmbeddings:
    p = resolve_provider()
    # Same local/hosted split as get_llm() and for the same reason — a hosted
    # embedding id would 404 against local Ollama once resolve_provider() has
    # fallen back. NOTE the dimension trap this doesn't (and can't) solve: if the
    # index was built with the hosted 3072-dim model and the gateway then drops
    # mid-session, every subsequent query embeds at 1024-dim and silently
    # mismatches the existing Chroma collection. That is an operational risk to
    # manage on demo day (reseed after any embedding-model change, don't let a
    # live fallback happen after the index is built), not something a client
    # constructor can fix.
    model = settings.LOCAL_EMBEDDING_MODEL if p["name"] == "local" else settings.EMBEDDING_MODEL
    return OpenAIEmbeddings(
        model=model,
        # Non-OpenAI models have no tiktoken encoding; skipping the length check keeps
        # gte-large working through the OpenAI-compatible client.
        check_embedding_ctx_length=False,
        **_client_kwargs(p["base_url"], p["api_key"]),
    )


# --- calls ------------------------------------------------------------------


def chat(
    prompt: str,
    system: str = "",
    tier: ModelTier | None = None,
    fast: bool = False,
    temperature: float | None = None,
    trace: Any = None,
) -> str:
    """Single-turn completion. Always time-capped."""
    messages: list[Any] = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=prompt))

    llm = get_llm(tier=tier, fast=fast, temperature=temperature)
    response: AIMessage = with_timeout(llm.invoke, messages)
    if trace is not None:
        trace.add_usage(response, model=llm.model_name)
    return (response.content or "").strip()


def chat_messages(
    messages: list[Any],
    tier: ModelTier | None = None,
    fast: bool = False,
    trace: Any = None,
) -> str:
    """Multi-turn completion for the chatbot path."""
    llm = get_llm(tier=tier, fast=fast)
    response: AIMessage = with_timeout(llm.invoke, messages)
    if trace is not None:
        trace.add_usage(response, model=llm.model_name)
    return (response.content or "").strip()


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def chat_json(
    prompt: str,
    system: str = "",
    tier: ModelTier | None = None,
    fast: bool = True,
    trace: Any = None,
    default: Any = None,
) -> Any:
    """Completion expected to return JSON.

    Small local models fence their output and add prose; this strips both. A parse
    failure returns `default` rather than raising, because every caller is a guardrail
    or a scorer that must not take down the request.

    Defaults to the fast tier (`fast=True`) because most JSON callers are guardrails
    and scorers — short, schema-bound, high-volume. Pass `tier="deep"` explicitly for
    the calls that warrant it (e.g. severity assessment); `tier`, when given, always
    wins over `fast`.
    """
    raw = chat(prompt, system=system, tier=tier, fast=fast, temperature=0, trace=trace)
    candidate = raw
    block = _JSON_BLOCK.search(raw)
    if block:
        candidate = block.group(1)
    else:
        start = min((i for i in (candidate.find("{"), candidate.find("[")) if i != -1), default=-1)
        end = max(candidate.rfind("}"), candidate.rfind("]"))
        if start != -1 and end > start:
            candidate = candidate[start : end + 1]
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        log.warning("chat_json failed to parse: %s", raw[:200])
        return default


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return with_timeout(get_embeddings().embed_documents, texts)


def embed_query(text: str) -> list[float]:
    if not text or not text.strip():
        return []
    return with_timeout(get_embeddings().embed_query, text)
