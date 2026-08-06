"""The two persistence layers, kept apart on purpose.

    db.sqlite    relational — users, sessions, messages, documents, audit, feedback, evals
    db.vectordb  vectors    — chunk text + embeddings + governance metadata (Chroma)

They answer different questions: SQLite does exact lookups, ordering and counting;
Chroma does approximate nearest-neighbour search. See docs/FLOW.md for the full
reasoning and how to inspect each one.
"""

import sys
from pathlib import Path

# Both layers read paths from backend/config.py. Put backend on the import path here
# so this package works the same whether it was loaded by the Flask app, the seed
# script, or the inspector.
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
