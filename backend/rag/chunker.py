"""Document -> chunks.

Recursive character splitting with overlap. Page numbers survive the split so
citations can point at a page, which is what makes them verifiable on stage.
"""

from __future__ import annotations

import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from guardrails.governance.access_control import acl_metadata
from rag.schemas import Chunk, RAGDocument

# Separator order matters: paragraph -> line -> sentence -> word.
# [PLACEHOLDER: add domain separators, e.g. "\nSECTION ", "\nCLAUSE " for contracts]
_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.CHUNK_SIZE,
    chunk_overlap=settings.CHUNK_OVERLAP,
    separators=_SEPARATORS,
    length_function=len,
)

PAGE_MARKER = "\n[[PAGE:{n}]]\n"


def chunk_document(doc: RAGDocument) -> list[Chunk]:
    """Split a document, carrying doc-level governance metadata onto every chunk."""
    doc_id = doc.id or uuid.uuid4().hex
    base_meta = {
        "doc_id": doc_id,
        "filename": doc.filename,
        "modality": doc.modality,
        "sensitivity": doc.sensitivity,
        # Human-readable copy for the UI...
        "allowed_roles": ",".join(doc.allowed_roles or ["admin"]),
        # ...plus the flat acl_<role> booleans the Chroma `where` clause filters on,
        # because metadata values must be scalars and a list is not filterable.
        **acl_metadata(doc.allowed_roles),
        **{k: str(v) for k, v in (doc.attributes or {}).items()},
    }

    chunks: list[Chunk] = []
    for ordinal, piece in enumerate(_splitter.split_text(doc.text)):
        page = _page_of(piece)
        text = _strip_markers(piece).strip()
        if not text:
            continue
        chunks.append(
            Chunk(
                id=f"{doc_id}-{ordinal}",
                doc_id=doc_id,
                text=text,
                ordinal=ordinal,
                page=page,
                metadata={**base_meta, "ordinal": ordinal, "page": page or 0},
            )
        )
    return chunks


def _page_of(piece: str) -> int | None:
    marker = piece.rfind("[[PAGE:")
    if marker == -1:
        return None
    end = piece.find("]]", marker)
    try:
        return int(piece[marker + 7 : end])
    except ValueError:
        return None


def _strip_markers(piece: str) -> str:
    out = []
    i = 0
    while True:
        start = piece.find("[[PAGE:", i)
        if start == -1:
            out.append(piece[i:])
            break
        out.append(piece[i:start])
        end = piece.find("]]", start)
        i = len(piece) if end == -1 else end + 2
    return "".join(out)
