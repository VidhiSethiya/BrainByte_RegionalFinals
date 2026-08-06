"""text -> vector, batched and time-capped.

Thin layer over ai/llm.py so nothing else needs to know an embedding model exists.
"""

from __future__ import annotations

from ai.llm import embed_query, embed_texts, parallel_map
from observability.telemetry import log

# Ollama handles modest batches best; larger batches raise tail latency sharply.
BATCH_SIZE = 32


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed in parallel batches. A failed batch yields zero-vectors for its rows
    rather than aborting the whole ingest."""
    if not texts:
        return []
    batches = [texts[i : i + BATCH_SIZE] for i in range(0, len(texts), BATCH_SIZE)]
    results = parallel_map(embed_texts, batches, seconds=180)

    vectors: list[list[float]] = []
    dim = 0
    for batch, result in zip(batches, results):
        if result:
            dim = dim or len(result[0])
            vectors.extend(result)
        else:
            log.error("embedding batch failed (%d texts) — inserting zero vectors", len(batch))
            vectors.extend([[0.0] * (dim or 1024)] * len(batch))
    return vectors


def embed_one(text: str) -> list[float]:
    return embed_query(text)
