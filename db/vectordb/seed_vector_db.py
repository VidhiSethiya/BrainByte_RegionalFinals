"""Load seed documents into Chroma.

    python db/vectordb/seed_vector_db.py            # index db/vectordb/data/seed/*
    python db/vectordb/seed_vector_db.py --reset    # drop the collection first
    python db/vectordb/seed_vector_db.py --path some/dir --roles admin,analyst

Uses the same `index_document` path as the upload API, so seeded and uploaded
documents are identical in the store. Idempotent: a document keeps its id, so
re-running replaces its chunks rather than duplicating them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
# Repo root so `db.*` resolves, backend/ so `config`/`rag` do. Both explicitly, because
# `from config import ...` below runs before db/__init__ would have added backend.
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "backend"))

from config import settings  # noqa: E402
from db.sqlite.models import init_db  # noqa: E402
from db.vectordb import vector_store  # noqa: E402
from observability.telemetry import log  # noqa: E402
from rag import rag_indexer  # noqa: E402
from rag.multimodal import IMAGE_SUFFIXES, TEXT_SUFFIXES  # noqa: E402

SUPPORTED = TEXT_SUFFIXES | IMAGE_SUFFIXES | {".pdf"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the vector database")
    parser.add_argument("--path", default=None, help="directory of documents")
    parser.add_argument("--reset", action="store_true", help="drop the collection first")
    parser.add_argument(
        "--roles",
        default="admin,analyst,viewer",
        help="comma-separated roles allowed to read these documents",
    )
    parser.add_argument("--sensitivity", default="internal")
    args = parser.parse_args()

    init_db()
    if args.reset:
        vector_store.reset()
        log.info("collection reset")

    directory = Path(args.path) if args.path else settings.SEED_DIR
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        log.error("no seed directory — created %s, put documents there and re-run", directory)
        return 1

    files = [
        p for p in sorted(directory.rglob("*")) if p.is_file() and p.suffix.lower() in SUPPORTED
    ]
    if not files:
        log.error("no supported files in %s (looked for %s)", directory, sorted(SUPPORTED))
        return 1

    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    total_chunks = 0
    failed = 0

    for path in files:
        try:
            result = rag_indexer.index_file(
                path,
                # Stable id from the filename keeps re-seeding idempotent.
                id=path.stem.lower().replace(" ", "-"),
                allowed_roles=roles,
                sensitivity=args.sensitivity,
            )
            total_chunks += result["chunks"]
            log.info("  %-40s %3d chunks", path.name, result["chunks"])
        except Exception as exc:  # noqa: BLE001 - report and continue
            failed += 1
            log.error("  %-40s FAILED: %s", path.name, exc)

    log.info(
        "seeded %d/%d files, %d chunks, collection now holds %d",
        len(files) - failed,
        len(files),
        total_chunks,
        vector_store.count(),
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
