"""Document ingest: PDF/DOCX/XLSX/PPTX/TXT/MD → sections → chunks → per-opportunity index.

Sections keep their heading path and page (or slide) number so every chunk can be cited as
``[3.2 Scope > Data Integration, p.14]``. Tables are emitted row-wise with their headers.
Token counts are approximated as ``len(text) / 4`` (see DECISIONS.md).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import statistics
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from studio.config import RagConfig
from studio.guards import resolve_in_sandbox, scan_phi
from studio.llm import LLMClient
from studio.models import Chunk, Section
from studio.rag import VectorIndex

StatusFn = Callable[[str], None]

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}
CHARS_PER_TOKEN = 4

# "3.2 Scope", "4 Evaluation", "1.1. Background" — short, starts with a capital, no final period.
_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+[A-Z][^\n]{0,80}$")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+")


class IngestError(ValueError):
    """A file could not be ingested. The message is user-facing."""


# --- helpers --------------------------------------------------------------------------------


def file_hash(path: Path) -> str:
    """SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\xa0", " ")).strip()


def _table_rows(rows: Sequence[Sequence[object]]) -> list[str]:
    """Render a table as one line per data row: ``Header: value; Header: value``."""
    cleaned = [[_clean(str(c)) if c is not None else "" for c in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return []
    header = [h or f"Column {i + 1}" for i, h in enumerate(cleaned[0])]
    lines = []
    for row in cleaned[1:]:
        pairs = [
            f"{header[i] if i < len(header) else f'Column {i + 1}'}: {v}"
            for i, v in enumerate(row)
            if v
        ]
        if pairs:
            lines.append("; ".join(pairs))
    if not lines:  # header-only table: keep its text
        lines.append("; ".join(h for h in cleaned[0] if h))
    return lines


class _SectionBuilder:
    """Accumulates paragraphs under a heading stack and flushes them into sections."""

    def __init__(self, file: str) -> None:
        self.file = file
        self.stack: list[tuple[int, str]] = []
        self.page: int | None = None
        self.paragraphs: list[str] = []
        self.sections: list[Section] = []

    @property
    def path(self) -> list[str]:
        return [title for _, title in self.stack]

    def flush(self) -> None:
        text = "\n\n".join(p for p in self.paragraphs if p)
        if text.strip():
            self.sections.append(
                Section(file=self.file, heading_path=self.path, page=self.page, text=text)
            )
        self.paragraphs = []

    def heading(self, level: int, title: str) -> None:
        self.flush()
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        self.stack.append((level, title))

    def set_page(self, page: int | None) -> None:
        if page != self.page:
            self.flush()
            self.page = page

    def paragraph(self, text: str) -> None:
        text = _clean(text)
        if text:
            self.paragraphs.append(text)

    def table(self, rows: Sequence[Sequence[object]]) -> None:
        lines = _table_rows(rows)
        if not lines:
            return
        self.flush()
        self.sections.append(
            Section(
                file=self.file,
                heading_path=self.path,
                page=self.page,
                text="\n".join(lines),
                kind="table",
            )
        )

    def finish(self) -> list[Section]:
        self.flush()
        return self.sections


def _numbered_level(text: str) -> int | None:
    match = _NUMBERED_HEADING.match(text)
    if not match or text.rstrip().endswith((".", ",", ":")):
        return None
    return match.group(1).count(".") + 1


# --- extractors -----------------------------------------------------------------------------


def _pdf_table_rows(page: Any, table: Any) -> list[list[str]]:
    """Cell text read from each cell's box (more faithful than ``Table.extract`` for spacing)."""
    return [
        [page.get_textbox(cell).replace("\n", " ") if cell else "" for cell in row.cells]
        for row in table.rows
    ]


def _extract_pdf(path: Path) -> list[Section]:
    import pymupdf

    builder = _SectionBuilder(path.name)
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # pymupdf raises several types for broken files
        raise IngestError(f"Could not open PDF {path.name}: {exc}") from exc

    with doc:
        # Pass 1: collect lines with font info so heading sizes can be judged against the body.
        pages: list[list[tuple[float, str, object]]] = []
        sizes: list[float] = []
        for page in doc:
            tables = list(page.find_tables().tables)
            items: list[tuple[float, str, object]] = [
                (t.bbox[1], "table", _pdf_table_rows(page, t)) for t in tables
            ]
            boxes = [pymupdf.Rect(t.bbox) for t in tables]
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    spans = [s for s in line["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    rect = pymupdf.Rect(line["bbox"])
                    if any(box.contains(rect.tl + (rect.br - rect.tl) * 0.5) for box in boxes):
                        continue
                    text = _clean("".join(s["text"] for s in spans))
                    size = max(s["size"] for s in spans)
                    bold = any(s["flags"] & 16 for s in spans)
                    sizes.extend([size] * len(text))
                    items.append((line["bbox"][1], "line", (text, size, bold, block["number"])))
            items.sort(key=lambda it: it[0])
            pages.append(items)

        body = statistics.median(sizes) if sizes else 10.0
        heading_sizes = sorted({round(s, 1) for s in sizes if s >= body * 1.15}, reverse=True)

        for page_no, items in enumerate(pages, start=1):
            builder.set_page(page_no)
            para: list[str] = []
            last_block = None
            for _, kind, payload in items:
                if kind == "table":
                    if para:
                        builder.paragraph(" ".join(para))
                        para = []
                    builder.table(payload)  # type: ignore[arg-type]
                    continue
                text, size, bold, block_no = payload  # type: ignore[misc]
                level = _numbered_level(text)
                big = round(size, 1) in heading_sizes and len(text) <= 120
                if big or (level is not None and (bold or size > body)):
                    if para:
                        builder.paragraph(" ".join(para))
                        para = []
                    if level is None:
                        level = heading_sizes.index(round(size, 1)) + 1
                    builder.heading(level, text)
                    last_block = None
                    continue
                if block_no != last_block and para:
                    builder.paragraph(" ".join(para))
                    para = []
                para.append(text)
                last_block = block_no
            if para:
                builder.paragraph(" ".join(para))
    return builder.finish()


def _extract_docx(path: Path) -> list[Section]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise IngestError(f"Could not open DOCX {path.name}: {exc}") from exc

    builder = _SectionBuilder(path.name)
    for element in document.element.body.iterchildren():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            table = Table(element, document)
            builder.table([[cell.text for cell in row.cells] for row in table.rows])
        elif tag == "p":
            para = Paragraph(element, document)
            text = _clean(para.text)
            if not text:
                continue
            style = (para.style.name if para.style is not None else "") or ""
            if style == "Title":  # same level as Heading 1, so it doesn't prefix every cite
                builder.heading(1, text)
            elif style.startswith("Heading"):
                digits = "".join(ch for ch in style if ch.isdigit())
                builder.heading(int(digits) if digits else 1, text)
            else:
                builder.paragraph(text)
    return builder.finish()


def _extract_xlsx(path: Path) -> list[Section]:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise IngestError(f"Could not open XLSX {path.name}: {exc}") from exc

    sections: list[Section] = []
    try:
        for sheet in workbook.worksheets:
            rows = [
                (idx, row)
                for idx, row in enumerate(sheet.iter_rows(values_only=True), start=1)
                if any(c not in (None, "") for c in row)
            ]
            if not rows:
                continue
            header_row = rows[0][1]
            lines = []
            for idx, row in rows[1:]:
                rendered = _table_rows([header_row, row])
                if rendered:
                    lines.append(f"Row {idx} — {rendered[0]}")
            if not lines:
                lines = _table_rows([header_row])
            sections.append(
                Section(
                    file=path.name, heading_path=[sheet.title], text="\n".join(lines), kind="table"
                )
            )
    finally:
        workbook.close()
    return sections


def _extract_pptx(path: Path) -> list[Section]:
    from pptx import Presentation

    try:
        prs = Presentation(str(path))
    except Exception as exc:
        raise IngestError(f"Could not open PPTX {path.name}: {exc}") from exc

    sections: list[Section] = []
    for slide_no, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        title = _clean(title_shape.text_frame.text) if title_shape is not None else ""
        heading = [title or f"Slide {slide_no}"]
        texts: list[str] = []
        title_id = title_shape.shape_id if title_shape is not None else None
        for shape in slide.shapes:
            if shape.shape_id == title_id:
                continue
            if shape.has_text_frame:
                texts.extend(_clean(p.text) for p in shape.text_frame.paragraphs if p.text.strip())
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
                lines = _table_rows(rows)
                if lines:
                    sections.append(
                        Section(
                            file=path.name,
                            heading_path=heading,
                            page=slide_no,
                            text="\n".join(lines),
                            kind="table",
                        )
                    )
        if slide.has_notes_slide:
            notes = _clean(slide.notes_slide.notes_text_frame.text)
            if notes:
                texts.append(f"Speaker notes: {notes}")
        if texts:
            sections.append(
                Section(
                    file=path.name, heading_path=heading, page=slide_no, text="\n\n".join(texts)
                )
            )
    return sections


def _extract_text(path: Path) -> list[Section]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise IngestError(f"Could not read {path.name}: {exc}") from exc

    builder = _SectionBuilder(path.name)
    markdown = path.suffix.lower() == ".md"
    para: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        md = _MD_HEADING.match(stripped) if markdown else None
        level = len(md.group(1)) if md else _numbered_level(stripped)
        if level is not None:
            if para:
                builder.paragraph(" ".join(para))
                para = []
            builder.heading(level, md.group(2) if md else stripped)
        elif not stripped:
            if para:
                builder.paragraph(" ".join(para))
                para = []
        else:
            para.append(stripped)
    if para:
        builder.paragraph(" ".join(para))
    return builder.finish()


_EXTRACTORS: dict[str, Callable[[Path], list[Section]]] = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".xlsx": _extract_xlsx,
    ".pptx": _extract_pptx,
    ".txt": _extract_text,
    ".md": _extract_text,
}


def extract_sections(path: Path) -> list[Section]:
    """Extract sections (heading path + page + text) from a supported document."""
    extractor = _EXTRACTORS.get(path.suffix.lower())
    if extractor is None:
        raise IngestError(
            f"{path.name}: unsupported file type. Supported: "
            + ", ".join(sorted(SUPPORTED_SUFFIXES))
        )
    return extractor(path)


# --- chunking -------------------------------------------------------------------------------


def _split_long(unit: str, max_chars: int) -> list[str]:
    """Split one oversized paragraph on sentence boundaries, then hard-split if needed."""
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT.split(unit):
        while len(sentence) > max_chars:  # no usable sentence break: cut at a space
            cut = sentence.rfind(" ", 0, max_chars)
            if cut <= max_chars // 2:
                cut = max_chars
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _tail(text: str, chars: int) -> str:
    if chars <= 0 or len(text) <= chars:
        return "" if chars <= 0 else text
    tail = text[-chars:]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) // 2 else tail


def chunk_sections(
    sections: Iterable[Section], file_hash_: str, tokens: int = 800, overlap: int = 100
) -> list[Chunk]:
    """Pack each section's paragraphs (or table rows) into ~``tokens`` chunks with ``overlap``.

    Chunks never span two sections, so each chunk has exactly one citation.
    """
    max_chars = tokens * CHARS_PER_TOKEN
    overlap_chars = overlap * CHARS_PER_TOKEN
    chunks: list[Chunk] = []

    def emit(section: Section, text: str) -> None:
        cid = hashlib.sha1(f"{file_hash_}:{len(chunks)}".encode()).hexdigest()[:16]
        chunks.append(
            Chunk(
                id=cid,
                file=section.file,
                file_hash=file_hash_,
                section=section.section_label,
                page=section.page,
                text=text,
            )
        )

    for section in sections:
        sep = "\n" if section.kind == "table" else "\n\n"
        units: list[str] = []
        for unit in section.text.split(sep):
            unit = unit.strip()
            if unit:
                units.extend(_split_long(unit, max_chars) if len(unit) > max_chars else [unit])
        current = ""
        for unit in units:
            candidate = f"{current}{sep}{unit}" if current else unit
            if current and len(candidate) > max_chars:
                emit(section, current)
                carry = _tail(current, overlap_chars)
                current = f"{carry}{sep}{unit}" if carry else unit
                if len(current) > max_chars:
                    current = unit
            else:
                current = candidate
        if current:
            emit(section, current)
    return chunks


# --- ingest ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class FilePhiHit:
    """A possible PHI match located in an ingested file."""

    file: str
    page: int | None
    kind: str
    excerpt: str


@dataclass
class IngestReport:
    """What an ingest run did. ``blocked`` means PHI was found and not confirmed."""

    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    chunks_added: int = 0
    total_chunks: int = 0
    phi_hits: list[FilePhiHit] = field(default_factory=list)
    blocked: bool = False


def _gather(input_dir: Path, paths: Sequence[Path]) -> list[tuple[Path, str]]:
    """(source path, name in input/) for each file to ingest."""
    if paths:
        targets = []
        for p in paths:
            if p.is_dir():
                targets.extend((f, f.name) for f in sorted(p.iterdir()) if f.is_file())
            elif p.is_file():
                targets.append((p, p.name))
            else:
                raise IngestError(f"File not found: {p}")
        return targets
    return [(f, f.name) for f in sorted(input_dir.iterdir()) if f.is_file()]


def ingest(
    opp_dir: Path,
    paths: Sequence[Path],
    llm: LLMClient,
    cfg: RagConfig,
    embed_model: str,
    *,
    confirm_phi: bool = False,
    on_status: StatusFn | None = None,
) -> IngestReport:
    """Ingest files into ``opp_dir``: copy into ``input/``, PHI-scan, chunk, update the index.

    With no ``paths``, everything in ``input/`` is (re)ingested and files no longer present are
    removed from the index. If possible PHI is found and ``confirm_phi`` is False, nothing is
    copied or indexed and the report comes back with ``blocked=True``.
    """
    status = on_status or (lambda _msg: None)
    input_dir = opp_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    index = VectorIndex(opp_dir / "index")
    if index.ensure_model(embed_model):
        status(f"Embedding model changed to {embed_model}; rebuilding the index.")

    report = IngestReport()
    pending: list[tuple[Path, str, str, list[Section]]] = []
    for src, name in _gather(input_dir, paths):
        if src.suffix.lower() not in SUPPORTED_SUFFIXES:
            report.skipped[name] = "unsupported file type"
            continue
        digest = file_hash(src)
        previous = index.file_hash(name)
        if previous == digest:
            report.unchanged.append(name)
            continue
        status(f"Reading {name}…")
        try:
            sections = extract_sections(src)
        except IngestError as exc:
            report.skipped[name] = str(exc)
            continue
        for section in sections:
            report.phi_hits.extend(
                FilePhiHit(name, section.page, hit.kind, hit.excerpt)
                for hit in scan_phi(section.text)
            )
        (report.changed if previous else report.new).append(name)
        pending.append((src, name, digest, sections))

    if report.phi_hits and not confirm_phi:
        report.blocked = True
        return report

    chunks_by_file: dict[str, tuple[str, list[Chunk]]] = {}
    for src, name, digest, sections in pending:
        dest = resolve_in_sandbox(input_dir, name)
        if src.resolve() != dest:
            shutil.copy2(src, dest)
        chunks = chunk_sections(sections, digest, cfg.chunk_tokens, cfg.chunk_overlap)
        chunks_by_file[name] = (digest, chunks)

    if not paths:
        present = {name for _, name in _gather(input_dir, paths)}
        for name in index.files():
            if name not in present:
                index.remove_file(name)
                report.removed.append(name)

    total_new = sum(len(c) for _, c in chunks_by_file.values())
    if total_new:
        status(f"Embedding {total_new} chunks…")
    for name, (digest, chunks) in chunks_by_file.items():
        vectors = llm.embed([c.text for c in chunks]) if chunks else []
        index.replace_file(name, digest, chunks, vectors)
    report.chunks_added = total_new
    index.save()
    report.total_chunks = len(index)
    return report
