"""Document viewer back end: PDF pages and text layers, reading views for Office/text files.

PDFs are rendered with pymupdf (already a dependency) at the width the side panel asks for and
cached per page in ``<project>/.studio-cache/pages/``. Other formats reuse
:func:`studio.ingest.extract_sections`, so the viewer shows exactly what was indexed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pymupdf

from studio.ingest import IngestError, extract_sections

CACHE_DIR = ".studio-cache"
MIN_W, MAX_W = 160, 2400
MAX_FIND = 200


class ViewError(ValueError):
    """The file can't be shown. User-facing."""


def kind_of(path: Path) -> str:
    """``pdf``, ``docx``, ``xlsx``, ``pptx``, ``txt`` or ``md``."""
    return path.suffix.lower().lstrip(".")


def _open_pdf(path: Path) -> pymupdf.Document:
    try:
        return pymupdf.open(path)
    except Exception as exc:  # pymupdf raises several types for broken files
        raise ViewError(f"{path.name} can't be opened as a PDF.") from exc


def meta(path: Path) -> dict[str, Any]:
    """Name, type, size, modified time, and (PDF) page count and sizes in points."""
    stat = path.stat()
    info: dict[str, Any] = {
        "name": path.name,
        "kind": kind_of(path),
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "pages": None,
        "page_sizes": [],
    }
    if info["kind"] == "pdf":
        with _open_pdf(path) as doc:
            info["pages"] = doc.page_count
            info["page_sizes"] = [[round(p.rect.width, 1), round(p.rect.height, 1)] for p in doc]
    return info


def _page(doc: pymupdf.Document, n: int) -> pymupdf.Page:
    if not 1 <= n <= doc.page_count:
        raise ViewError(f"Page {n} doesn't exist (1–{doc.page_count}).")
    return doc[n - 1]


def render_page(path: Path, n: int, width: int, cache_root: Path) -> bytes:
    """PNG of page ``n`` (1-based) at ``width`` pixels, cached by file content and size."""
    width = max(MIN_W, min(MAX_W, int(width)))
    stat = path.stat()
    key = hashlib.sha1(f"{path.name}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()[:16]
    cached = cache_root / CACHE_DIR / "pages" / f"{key}-{n}-{width}.png"
    if cached.is_file():
        return cached.read_bytes()
    with _open_pdf(path) as doc:
        page = _page(doc, n)
        zoom = width / page.rect.width
        png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(png)
    return png


def page_words(path: Path, n: int) -> dict[str, Any]:
    """Words on page ``n`` (boxes in points): ``{width, height, words: [[x0, y0, x1, y1, w]]}``."""
    with _open_pdf(path) as doc:
        page = _page(doc, n)
        words = [[round(w[0], 1), round(w[1], 1), round(w[2], 1), round(w[3], 1), w[4]]
                 for w in page.get_text("words")]  # fmt: skip
        return {"width": page.rect.width, "height": page.rect.height, "words": words}


def sections(path: Path) -> list[dict[str, Any]]:
    """Reading view for any supported file: heading path, page/slide/sheet, text, kind."""
    try:
        found = extract_sections(path)
    except IngestError as exc:
        raise ViewError(str(exc)) from exc
    return [
        {"heading": s.heading_path, "page": s.page, "text": s.text, "kind": s.kind} for s in found
    ]


def find(path: Path, query: str) -> list[dict[str, Any]]:
    """Matches of ``query``: PDF → ``{page, rects}``; others → ``{section, page}``."""
    q = " ".join(query.split())
    if len(q) < 2:
        return []
    hits: list[dict[str, Any]] = []
    if kind_of(path) == "pdf":
        with _open_pdf(path) as doc:
            for page in doc:
                rects = page.search_for(q)
                if rects:
                    hits.append({
                        "page": page.number + 1,
                        "rects": [[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)]
                                  for r in rects],
                    })  # fmt: skip
                if sum(len(h["rects"]) for h in hits) >= MAX_FIND:
                    break
        return hits
    low = q.lower()
    for i, s in enumerate(sections(path)):
        if low in " ".join(s["text"].split()).lower():
            hits.append({"section": i, "page": s["page"]})
            if len(hits) >= MAX_FIND:
                break
    return hits
