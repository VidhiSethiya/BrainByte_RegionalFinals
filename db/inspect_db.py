"""Look inside both stores.

    python db/inspect_db.py                 # summary of SQLite + Chroma
    python db/inspect_db.py --chunks 10     # show more indexed chunks
    python db/inspect_db.py --sql "select username, role from users"

Read-only. Safe to run while the server is up.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "backend"))

# Paths are derived from this file's location, not from config, so the SQLite half
# works on a bare Python with no dependencies installed - which is when you most need
# to look inside. config is consulted only if it imports cleanly.
DB_PATH = _HERE / "sqlite" / "data" / "app.db"
CHROMA_DIR = _HERE / "vectordb" / "data" / "chroma"
COLLECTION = "knowledge_base"

try:
    from config import settings

    DB_PATH = Path(settings.DATABASE_URL.replace("sqlite:///", ""))
    CHROMA_DIR = settings.CHROMA_PERSIST_DIR
    COLLECTION = settings.CHROMA_COLLECTION
except Exception:  # noqa: BLE001 - deps missing is fine; defaults above still work
    pass

# Table -> the columns worth printing. Anything not listed is counted only.
PREVIEW = {
    "users": "username, role, clearances",
    "documents": "filename, modality, sensitivity, chunk_count, status",
    "chat_sessions": "title, substr(coalesce(summary,''), 1, 60)",
    "chat_messages": "role, substr(content, 1, 70), groundedness",
    "audit_log": "action, resource, created_at",
    "feedback": "message_id, rating, reviewed",
    "eval_results": "substr(question, 1, 50), groundedness, latency_ms",
}


def show_sqlite(limit: int) -> None:
    print(f"\n=== SQLite  {DB_PATH} ===")
    if not DB_PATH.exists():
        print("  not created yet - start the backend once (python backend/run.py)")
        return

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    tables = [r[0] for r in conn.execute(
        "select name from sqlite_master where type='table' order by name"
    )]

    for table in tables:
        count = conn.execute(f"select count(*) from {table}").fetchone()[0]
        print(f"\n  {table}  ({count} rows)")
        columns = PREVIEW.get(table)
        if not columns or count == 0:
            continue
        order = "order by rowid desc" if table in {"chat_messages", "audit_log"} else ""
        for row in conn.execute(f"select {columns} from {table} {order} limit {limit}"):
            print("    ", " | ".join("" if v is None else str(v) for v in row))
    conn.close()


def show_chroma(limit: int) -> None:
    print(f"\n=== Chroma  {CHROMA_DIR} ===")
    try:
        from db.vectordb import vector_store
    except Exception as exc:  # noqa: BLE001 - missing deps, not a crash
        print(f"  unavailable ({type(exc).__name__}: {exc})")
        print("  install backend requirements to inspect the vector store")
        return

    total = vector_store.count()
    print(f"  collection '{COLLECTION}': {total} chunks")
    if total == 0:
        print("  empty - run: python db/vectordb/seed_vector_db.py --reset")
        return

    for chunk in vector_store.all_chunks()[:limit]:
        meta = chunk["metadata"]
        text = chunk["text"][:80].replace("\n", " ")
        page = f" p.{meta.get('page')}" if meta.get("page") else ""
        print(f"    {meta.get('filename', '?')}{page} | {text}")


def check_drift() -> None:
    """The documents table and Chroma must agree on chunk counts."""
    print("\n=== Consistency ===")
    if not DB_PATH.exists():
        return
    try:
        from db.vectordb import vector_store
    except Exception:  # noqa: BLE001 - cannot compare without the vector store
        print("  skipped - vector store unavailable")
        return

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = conn.execute("select id, filename, chunk_count from documents").fetchall()
    conn.close()
    if not rows:
        print("  no documents indexed yet")
        return

    actual: dict[str, int] = {}
    for chunk in vector_store.all_chunks():
        doc_id = chunk["metadata"].get("doc_id", "")
        actual[doc_id] = actual.get(doc_id, 0) + 1

    for doc_id, filename, expected in rows:
        found = actual.get(doc_id, 0)
        status = "OK   " if found == expected else "DRIFT"
        print(f"  {status} {filename}: sqlite={expected} chroma={found}")

    if any(actual.get(d, 0) != n for d, _, n in rows):
        print("\n  DRIFT means an index run failed halfway.")
        print("  Fix: re-upload that document, or python db/vectordb/seed_vector_db.py --reset")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the SQLite and Chroma stores")
    parser.add_argument("--rows", type=int, default=5, help="rows per SQLite table")
    parser.add_argument("--chunks", type=int, default=5, help="chunks to preview")
    parser.add_argument("--sql", help="run one read-only query against app.db")
    args = parser.parse_args()

    if args.sql:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        for row in conn.execute(args.sql):
            print(" | ".join("" if v is None else str(v) for v in row))
        conn.close()
        return 0

    show_sqlite(args.rows)
    show_chroma(args.chunks)
    check_drift()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
