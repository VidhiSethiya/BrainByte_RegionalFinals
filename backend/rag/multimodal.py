"""Any file -> RAGDocument.

Three modalities are wired: plain text, PDF (text + page images), and images.
PDFs are the interesting case: a page with almost no extractable text is a scan or a
diagram, so it is rendered and sent to a vision model instead of being silently
indexed as an empty chunk. That single rule is what makes retrieval work on real
enterprise document sets.

Vision model id comes only from `settings.VISION_MODEL` (config.py) — never hard-coded.
TicketSphere uses this for runbook PDFs and ~20 error/console screenshots in the seed.
"""

from __future__ import annotations

import base64
import mimetypes
import uuid
from pathlib import Path

from ai.llm import get_llm, with_timeout
from ai.prompts import IMAGE_DESCRIBE_PROMPT
from config import settings
from observability.telemetry import log
from rag.chunker import PAGE_MARKER
from rag.schemas import RAGDocument

TEXT_SUFFIXES = {".txt", ".md", ".log", ".csv", ".json"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# A page yielding fewer characters than this is treated as visual, not textual.
MIN_PAGE_CHARS = 120


def load_file(path: str | Path, **doc_kwargs) -> RAGDocument:
    """Dispatch on suffix. Unknown suffixes are read as text."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text, modality = _load_pdf(path), "pdf"
    elif suffix in IMAGE_SUFFIXES:
        text, modality = describe_image(path), "image"
    else:
        text, modality = path.read_text(encoding="utf-8", errors="ignore"), "text"
        if suffix not in TEXT_SUFFIXES:
            log.warning("unknown suffix %s — read as plain text", suffix)

    return RAGDocument(
        id=doc_kwargs.pop("id", None) or uuid.uuid4().hex,
        filename=path.name,
        text=text,
        modality=modality,
        source=str(path),
        **doc_kwargs,
    )


def load_text(filename: str, text: str, **doc_kwargs) -> RAGDocument:
    return RAGDocument(
        id=doc_kwargs.pop("id", None) or uuid.uuid4().hex,
        filename=filename,
        text=text,
        modality="text",
        **doc_kwargs,
    )


def _load_pdf(path: Path) -> str:
    import fitz  # PyMuPDF

    parts: list[str] = []
    with fitz.open(path) as pdf:
        for number, page in enumerate(pdf, start=1):
            text = page.get_text().strip()
            if len(text) < MIN_PAGE_CHARS:
                text = _describe_pdf_page(page, path.name, number) or text
            parts.append(PAGE_MARKER.format(n=number) + text)
    return "\n".join(parts)


def _describe_pdf_page(page, filename: str, number: int) -> str:
    """Render a low-text page and let a vision model read it."""
    try:
        pixmap = page.get_pixmap(dpi=150)
        return _vision_call(pixmap.tobytes("png"), "image/png")
    except Exception as exc:  # noqa: BLE001 - a bad page must not kill the ingest
        log.warning("vision fallback failed for %s p%d: %s", filename, number, exc)
        return ""


def describe_image(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    try:
        return _vision_call(path.read_bytes(), mime)
    except Exception as exc:  # noqa: BLE001
        log.warning("image description failed for %s: %s", path.name, exc)
        return f"[image: {path.name} — no description available]"


def _vision_call(raw: bytes, mime: str) -> str:
    """Multimodal message in the OpenAI content-parts format.

    Requires VISION_MODEL to name a vision-capable model. The default text-only local
    model cannot do this, so with no vision model configured we return empty and the
    caller falls back to whatever text was extractable.
    """
    if not settings.VISION_MODEL:
        return ""

    encoded = base64.b64encode(raw).decode()
    llm = get_llm().bind(model=settings.VISION_MODEL)
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": IMAGE_DESCRIBE_PROMPT.format(domain=settings.DOMAIN)},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ],
    }
    response = with_timeout(llm.invoke, [message], seconds=90)
    return (response.content or "").strip()
