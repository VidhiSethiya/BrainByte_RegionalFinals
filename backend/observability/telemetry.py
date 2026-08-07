"""Tracing, token accounting and usage analytics.

One `Trace` per request that touches an LLM. Stages are recorded as they run, so a
failed request still yields a partial trace — that is what makes the Traces tab
useful during a demo.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("app")

# Ring buffer of recent traces. Survives only for the process lifetime, which is all
# a demo needs; durable per-message telemetry lives on ChatMessage rows.
_TRACES: deque[dict] = deque(maxlen=200)
_LOCK = threading.Lock()

# Cost per 1M tokens, as (input_usd, output_usd). Keyed by the exact model string
# passed to ChatOpenAI(model=...) / OpenAIEmbeddings(model=...) — see
# config.py's LLM_MODEL / FAST_LLM_MODEL / REASONING_MODEL / EMBEDDING_MODEL.
#
# HONEST LIMITATION: the TCS AI Fridays LiteLLM gateway does not publish a
# per-token invoice to participants, so these are not real billed rates. They are
# public list prices for the underlying model family (OpenAI's published pricing
# for the GPT-4.1 family and text-embedding-3-large; gpt-5.1's row is an estimate
# in the same band as other frontier reasoning models, since no public price
# exists for it at build time). They exist so the cost ticker and "cost per
# decision" story are directionally real and comparable *across tiers* — the
# point being proved is "deep costs ~10x fast, so spend it only where it earns
# its keep" — not a claim that this is what TCS is actually billed. Say so if a
# judge asks; it is a better answer than a confident wrong number.
#
# Local Ollama models are free — omitted here, so cost_usd naturally falls back
# to (0.0, 0.0) via PRICING.get(model, (0.0, 0.0)) below.
PRICING: dict[str, tuple[float, float]] = {
    # --- deep tier ---
    "genailab-maas-gpt-5.1": (3.00, 15.00),  # [ESTIMATE] no public price at build time
    # --- standard tier ---
    "azure/genailab-maas-gpt-4.1": (2.00, 8.00),
    # --- fast tier (~70% of calls) ---
    "azure/genailab-maas-gpt-4.1-mini": (0.40, 1.60),
    # --- embeddings (input-only cost) ---
    "azure/genailab-maas-text-embedding-3-large": (0.13, 0.0),
    # --- vision ---
    "azure_ai/genailab-maas-Llama-3.2-90B-Vision-Instruct": (0.35, 0.40),  # [ESTIMATE]
    # Whisper is billed per-minute of audio, not per-token — deliberately absent
    # here; voice cost is not part of the per-decision token cost story.
}


@dataclass
class Stage:
    name: str
    ms: int
    meta: dict = field(default_factory=dict)


class Trace:
    """Context manager collecting one end-to-end request trace.

        with Trace("chat", user_id) as t:
            with t.stage("retrieve") as s:
                ...
                s.meta["chunks"] = len(chunks)
    """

    def __init__(self, name: str, user_id: str | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.user_id = user_id
        self.stages: list[Stage] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.model = ""
        self.error: str | None = None
        self._start = 0.0
        self.total_ms = 0

    def __enter__(self) -> "Trace":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.total_ms = int((time.perf_counter() - self._start) * 1000)
        if exc:
            self.error = f"{exc_type.__name__}: {exc}"
        with _LOCK:
            _TRACES.appendleft(self.to_dict())
        log.info(
            "%s trace=%s %dms tokens=%d/%d%s",
            self.name,
            self.id,
            self.total_ms,
            self.prompt_tokens,
            self.completion_tokens,
            f" ERROR {self.error}" if self.error else "",
        )
        return False  # never swallow the exception

    def stage(self, name: str) -> "_StageCtx":
        return _StageCtx(self, name)

    def add_usage(self, response: Any, model: str = "") -> None:
        """Pull token counts off a LangChain AIMessage."""
        meta = getattr(response, "usage_metadata", None) or {}
        self.prompt_tokens += int(meta.get("input_tokens", 0) or 0)
        self.completion_tokens += int(meta.get("output_tokens", 0) or 0)
        if model:
            self.model = model

    @property
    def cost_usd(self) -> float:
        rate_in, rate_out = PRICING.get(self.model, (0.0, 0.0))
        return round(
            (self.prompt_tokens * rate_in + self.completion_tokens * rate_out) / 1_000_000, 6
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "user_id": self.user_id,
            "total_ms": self.total_ms,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "cost_usd": self.cost_usd,
            "error": self.error,
            "stages": [{"name": s.name, "ms": s.ms, **s.meta} for s in self.stages],
            "ts": time.time(),
        }


class _StageCtx:
    def __init__(self, trace: Trace, name: str):
        self.trace = trace
        self.name = name
        self.meta: dict = {}
        self._start = 0.0

    def __enter__(self) -> "_StageCtx":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        ms = int((time.perf_counter() - self._start) * 1000)
        if exc:
            self.meta["error"] = str(exc)
        self.trace.stages.append(Stage(self.name, ms, self.meta))
        return False


def recent_traces(limit: int = 50) -> list[dict]:
    with _LOCK:
        return list(_TRACES)[:limit]


def usage_summary() -> dict:
    """Aggregates for the Analytics tab. Cheap enough to recompute per request."""
    with _LOCK:
        traces = list(_TRACES)
    if not traces:
        return {
            "requests": 0,
            "avg_latency_ms": 0,
            "p95_latency_ms": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "error_rate": 0.0,
        }
    latencies = sorted(t["total_ms"] for t in traces)
    return {
        "requests": len(traces),
        "avg_latency_ms": int(sum(latencies) / len(latencies)),
        "p95_latency_ms": latencies[int(len(latencies) * 0.95) - 1],
        "total_tokens": sum(t["total_tokens"] for t in traces),
        "total_cost_usd": round(sum(t["cost_usd"] for t in traces), 4),
        "error_rate": round(sum(1 for t in traces if t["error"]) / len(traces), 3),
    }
