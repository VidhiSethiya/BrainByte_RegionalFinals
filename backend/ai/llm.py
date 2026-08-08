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
        # LLM_BASE_URL/LLM_API_KEY, not OPENAI_BASE_URL/OPENAI_API_KEY — chat's
        # provider is independent of embeddings' (see config.py::LLM_BASE_URL).
        "base_url": settings.LLM_BASE_URL,
        "api_key": settings.LLM_API_KEY,
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


def _effective_temperature(model: str, temperature: float) -> float:
    """Clamp temperature for models that reject deterministic sampling.

    GenAI Lab / LiteLLM: gpt-5* (incl. genailab-maas-gpt-5.1) reject temperature=0
    and only accept temperature=1. Without this, every deep-tier chat_json call
    (severity / reflect) dies with UnsupportedParamsError mid-triage.
    """
    name = model.lower()
    if "gpt-5" in name or "/o1" in name or name.startswith("o1") or "/o3" in name:
        return 1.0
    return temperature


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

    temp = settings.LLM_TEMPERATURE if temperature is None else temperature
    return ChatOpenAI(
        model=model,
        temperature=_effective_temperature(model, temp),
        max_retries=settings.LLM_MAX_RETRIES,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        **_client_kwargs(p["base_url"], p["api_key"]),
    )


@lru_cache(maxsize=1)
def get_embeddings() -> OpenAIEmbeddings:
    """The hosted `EMBEDDING_MODEL` (text-embedding-3-large) — the only client
    `get_embeddings()` itself builds, and what every normal call uses.

    Deliberately does NOT follow `resolve_provider()`'s local/hosted split the way
    `get_llm()` does. Chat can safely fall back to local Ollama mid-session because
    every chat call is independent — but embeddings are not: every chunk already in
    Chroma was embedded with one model's vector space, and mixing in a
    different-dimension model (e.g. a local one) would silently corrupt similarity
    search against the existing index, or fail outright on a dimension mismatch.
    See .claude/plans/rag-handoff.md §3 ("do not change without full reseed") and
    rag.md's known-risks table.

    `embed_texts()`/`embed_query()` below hold an emergency-only exception to this:
    if the hosted call itself raises (a genailab.tcs.in outage, not just a slow
    response), they fall back to a local model rather than dead-lettering every
    ticket for the outage's duration. That fallback is a deliberate, logged,
    stopgap trade-off — not a return to the old local/hosted split this function
    used to have.
    """
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        # Non-OpenAI-native models have no tiktoken encoding; skipping the length
        # check keeps them working through the OpenAI-compatible client.
        check_embedding_ctx_length=False,
        **_client_kwargs(settings.OPENAI_BASE_URL, settings.OPENAI_API_KEY),
    )


@lru_cache(maxsize=1)
def _local_embeddings() -> OpenAIEmbeddings:
    """Emergency-only fallback client — see get_embeddings()'s docstring. Never
    called directly by retrieval/indexing code; only embed_texts()/embed_query()
    reach for this, and only after the hosted call has already failed."""
    return OpenAIEmbeddings(
        model=settings.LOCAL_EMBEDDING_MODEL,
        check_embedding_ctx_length=False,
        **_client_kwargs(settings.LOCAL_BASE_URL, settings.LOCAL_API_KEY),
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
    try:
        return with_timeout(get_embeddings().embed_documents, texts)
    except Exception as exc:  # noqa: BLE001 - hosted outage; try the stopgap, not silence
        log.warning(
            "hosted embeddings failed (%s) -> falling back to local %s for %d chunk(s). "
            "These are in a DIFFERENT vector space than the rest of Chroma — reseed "
            "once the hosted gateway recovers.",
            exc, settings.LOCAL_EMBEDDING_MODEL, len(texts),
        )
        return with_timeout(_local_embeddings().embed_documents, texts)


def embed_query(text: str) -> list[float]:
    if not text or not text.strip():
        return []
    try:
        return with_timeout(get_embeddings().embed_query, text)
    except Exception as exc:  # noqa: BLE001 - hosted outage; try the stopgap, not silence
        log.warning(
            "hosted embeddings failed (%s) -> falling back to local %s for a query. "
            "Results will be unreliable against a hosted-embedded index until reseeded.",
            exc, settings.LOCAL_EMBEDDING_MODEL,
        )
        return with_timeout(_local_embeddings().embed_query, text)
