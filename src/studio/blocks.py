"""Block library: harvest reusable, anonymised blocks from past proposals, and search them.

``/harvest`` reads ``library/proposals/`` (one unit per PPTX slide or DOCX/PDF section), asks the
worker model for a client-neutral block, then anonymises again in Python (client names →
``{{client}}``, dates → ``{{date}}``, amounts → ``{{amount}}``). Blocks are human-editable YAML in
``library/blocks/<slide_type>/<id>.yaml``; the human is the curator, so harvest never overwrites
a block that was edited (``edited: true`` or content changed since harvest).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from studio.config import DeckConfig
from studio.deck.schemas import SLIDE_TYPES
from studio.ingest import SUPPORTED_SUFFIXES, IngestError, extract_sections
from studio.llm import LLMClient, Message, StructuredOutputError
from studio.models import Chunk
from studio.rag import VectorIndex

StatusFn = Callable[[str], None]
HARVEST_TYPES = tuple(t for t in SLIDE_TYPES if t != "title")
_YAML_HEADER = (
    "# Proposal Studio block. Edit freely: harvest never overwrites edited blocks.\n"
    "# Set needs_review: false once you've checked it is client-neutral.\n"
)


class BlockError(ValueError):
    """Block library problem. The message is user-facing."""


class Block(BaseModel):
    """A reusable, client-neutral piece of proposal content."""

    model_config = ConfigDict(extra="forbid")

    id: str
    slide_type: str
    title: str
    body_points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    capability: str = ""
    source_file: str = ""
    source_ref: str = ""
    edited: bool = False
    needs_review: bool = False
    review_notes: list[str] = Field(default_factory=list)
    content_hash: str = ""
    source_hash: str = ""

    def text(self) -> str:
        """Plain text used for embedding and prompts."""
        points = "\n".join(f"- {p}" for p in self.body_points)
        return f"{self.title}\n{points}\nTags: {', '.join(self.tags)}"


def compute_content_hash(block: Block) -> str:
    """Hash of the curated content (what a human would edit)."""
    payload = [block.slide_type, block.title, block.body_points, block.tags, block.capability]
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()[:16]


# --- anonymisation --------------------------------------------------------------------------

_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RE = re.compile(
    rf"\b(?:{_MONTHS}\s+(?:\d{{1,2}}(?:st|nd|rd|th)?,?\s+)?\d{{4}}|{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?"
    r"|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|q[1-4]\s+\d{4}|fy\s?\d{2,4}|(?:19|20)\d{2})\b",
    re.I,
)
MONEY_RE = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:k|m|mm|bn|b|million|billion|thousand))?\b"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:million|billion)\b(?:\s(?:dollars|usd))?)",
    re.I,
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?:\+1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_FIGURE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|x\b|percent\b)", re.I)


def anonymise(text: str, client_names: Sequence[str]) -> str:
    """Replace client names, dates and amounts with placeholders; drop emails and phones."""
    for name in sorted(
        {n.strip() for n in client_names if len(n.strip()) >= 3}, key=len, reverse=True
    ):
        text = re.sub(rf"\b{re.escape(name)}(?:'s)?\b", "{{client}}", text, flags=re.I)
    text = _EMAIL.sub("", text)
    text = _PHONE.sub("", text)
    text = MONEY_RE.sub("{{amount}}", text)
    text = DATE_RE.sub("{{date}}", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def review_figures(texts: Sequence[str]) -> list[str]:
    """Review notes for figures left in the text (they may be client-specific outcomes)."""
    found = sorted({m.group(0).strip() for t in texts for m in _FIGURE.finditer(t)})
    return (
        [f"contains figure(s) {', '.join(found)}: check they aren't client-specific"]
        if found
        else []
    )


# --- harvest --------------------------------------------------------------------------------


class HarvestResult(BaseModel):
    """What the model extracts from one slide or section."""

    reusable: bool
    slide_type: Literal[
        "understanding",
        "before_after",
        "solution_architecture",
        "ai_enablement",
        "platform",
        "governance",
        "maturity",
        "practice_leadership",
        "why_us",
        "next_steps",
        "other",
    ]
    title: str
    body_points: list[str]
    tags: list[str]
    capability: str
    client_names: list[str]
    uncertain: list[str]


_SYSTEM = """You turn one slide or section of a past proposal into a reusable, client-neutral
content block for future proposals.
- reusable=false for content that only makes sense for that client: pricing, team bios,
  contract terms, cover pages, agendas, thank-you slides.
- slide_type: the storyline slide it fits best:
  understanding (client challenges), before_after (current vs future state),
  solution_architecture (layers/components), ai_enablement (AI advantages), platform (AI
  platform: development, MLOps/LLMOps, observability, governance), governance (responsible AI,
  security, HIPAA/HITRUST), maturity (roadmap/maturity model), practice_leadership (AI
  practice, leadership, insights), why_us (differentiators), next_steps (engagement plan);
  "other" if none fits.
- title: at most 70 characters. body_points: 3-5 points, each at most 110 characters, phrased
  generically. Write {{client}} instead of the client's name.
- Remove people's names, dates, prices and figures that describe one client's results.
- client_names: every client or organisation name that appeared (so it can be removed).
- tags: 3-6 lowercase keywords (e.g. fhir, mlops, hipaa). capability: a short label.
- uncertain: only statements that might identify the client or be confidential (usually
  empty). Do not list names you already put in client_names."""


@dataclass
class HarvestReport:
    """What a harvest run did."""

    new: list[str] = field(default_factory=list)
    refreshed: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)
    unchanged: int = 0
    skipped: int = 0  # not reusable, "other", or too short
    failed: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)  # needs_review


def blocks_dir(root: Path) -> Path:
    """``library/blocks/``."""
    return root / "library" / "blocks"


def _state_path(root: Path) -> Path:
    return root / "library" / ".index" / "harvest.json"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "block"


def _units(path: Path, min_chars: int) -> list[tuple[str, str]]:
    """(source_ref, text) per PPTX slide or DOCX/PDF/TXT section."""
    sections = extract_sections(path)
    grouped: dict[str, list[str]] = {}
    for s in sections:
        if path.suffix.lower() == ".pptx":
            ref = f"slide {s.page}"
        else:
            ref = s.section_label + (f", p.{s.page}" if s.page else "")
        heading = " > ".join(s.heading_path)
        grouped.setdefault(ref, [heading] if heading else []).append(s.text)
    return [
        (ref, "\n".join(parts))
        for ref, parts in grouped.items()
        if len("".join(parts)) >= min_chars
    ]


def block_path(root: Path, block: Block) -> Path:
    """Where a block's YAML lives."""
    return blocks_dir(root) / block.slide_type / f"{block.id}.yaml"


def save_block(root: Path, block: Block) -> Path:
    """Write a block as YAML."""
    path = block_path(root, block)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(block.model_dump(), sort_keys=False, allow_unicode=True, width=100)
    path.write_text(_YAML_HEADER + body, encoding="utf-8")
    return path


def load_blocks(root: Path) -> list[Block]:
    """Every block in ``library/blocks`` (invalid files raise :class:`BlockError`)."""
    out = []
    for path in sorted(blocks_dir(root).glob("*/*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            out.append(Block.model_validate(data))
        except (yaml.YAMLError, ValueError) as exc:
            raise BlockError(f"{path} is not a valid block: {exc}") from exc
    return out


def is_protected(block: Block) -> bool:
    """True if a human edited the block (flag set, or content changed since harvest)."""
    return block.edited or (
        bool(block.content_hash) and compute_content_hash(block) != block.content_hash
    )


def _build_block(
    result: HarvestResult, unit_key: str, ref: str, file: str, digest: str, clients: Sequence[str]
) -> Block:
    names = [*result.client_names, *clients]
    title = anonymise(result.title, names)
    points = [p for p in (anonymise(p, names) for p in result.body_points) if p]
    block = Block(
        id=f"{_slug(title)}-{hashlib.sha1(unit_key.encode()).hexdigest()[:6]}",
        slide_type=result.slide_type,
        title=title,
        body_points=points,
        tags=sorted({t.strip().lower() for t in result.tags if t.strip()}),
        capability=anonymise(result.capability, names),
        source_file=file,
        source_ref=ref,
        source_hash=digest,
    )
    content = " ".join([title, *points]).lower()
    unsure = [anonymise(u, names) for u in result.uncertain]
    unsure = [
        u
        for u in unsure
        if u.strip("{} ").lower() not in ("client", "") and u.lower() not in content
    ]
    notes = [f"model unsure: {u}" for u in dict.fromkeys(unsure)] + review_figures([title, *points])
    block.needs_review, block.review_notes = bool(notes), notes
    block.content_hash = compute_content_hash(block)
    return block


def harvest(
    root: Path,
    llm: LLMClient,
    cfg: DeckConfig,
    *,
    source: Path | None = None,
    clients: Sequence[str] = (),
    on_status: StatusFn | None = None,
) -> HarvestReport:
    """Harvest blocks from ``source`` (default ``library/proposals``) into ``library/blocks``."""
    status = on_status or (lambda _msg: None)
    source = source or root / "library" / "proposals"
    if not source.exists():
        raise BlockError(f"No past proposals at {source}. Put PPTX/DOCX/PDF files there first.")
    files = (
        [source]
        if source.is_file()
        else sorted(p for p in source.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES)
    )
    state_path = _state_path(root)
    state: dict[str, dict[str, str]] = (
        json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    )
    existing = {b.id: b for b in load_blocks(root)}
    report = HarvestReport()

    units = []
    for path in files:
        try:
            units.extend((path, ref, text) for ref, text in _units(path, cfg.harvest_min_chars))
        except IngestError as exc:
            report.failed.append(f"{path.name}: {exc}")
    for n, (path, ref, text) in enumerate(units, start=1):
        unit_key = f"{path.name}#{ref}"
        digest = hashlib.sha1(text.encode()).hexdigest()[:16]
        if state.get(unit_key, {}).get("source_hash") == digest:
            report.unchanged += 1
            continue
        status(f"Harvesting {path.name} {ref} ({n}/{len(units)})…")
        messages: list[Message] = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Source: {path.name}, {ref}\n\n{text[:6000]}"},
        ]
        try:
            result = llm.generate_structured("worker", messages, HarvestResult)
        except StructuredOutputError:
            report.failed.append(f"{unit_key}: invalid model output")
            continue
        if not result.reusable or result.slide_type == "other" or not result.title.strip():
            report.skipped += 1
            state[unit_key] = {"source_hash": digest, "block": ""}
            continue

        block = _build_block(result, unit_key, ref, path.name, digest, clients)
        previous_id = state.get(unit_key, {}).get("block") or ""
        old = existing.get(previous_id) or existing.get(block.id)
        if old is not None:
            if is_protected(old):
                report.protected.append(old.id)
                state[unit_key] = {"source_hash": digest, "block": old.id}
                continue
            block = block.model_copy(update={"id": old.id})
            if old.slide_type != block.slide_type:
                block_path(root, old).unlink(missing_ok=True)
            report.refreshed.append(block.id)
        else:
            report.new.append(block.id)
        save_block(root, block)
        existing[block.id] = block
        if block.needs_review:
            report.flagged.append(block.id)
        state[unit_key] = {"source_hash": digest, "block": block.id}

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return report


# --- search ---------------------------------------------------------------------------------


def sync_index(
    root: Path, blocks: Sequence[Block], llm: LLMClient, embed_model: str
) -> VectorIndex:
    """Make ``library/.index/blocks`` match the YAML blocks (re-embeds changed ones)."""
    index = VectorIndex(root / "library" / ".index" / "blocks")
    index.ensure_model(embed_model)
    wanted = {b.id: b for b in blocks}
    for name in index.files():
        if name not in wanted:
            index.remove_file(name)
    changed = [b for b in blocks if index.file_hash(b.id) != compute_content_hash(b)]
    if changed:
        vectors = llm.embed([b.text() for b in changed])
        for block, vector in zip(changed, vectors, strict=True):
            digest = compute_content_hash(block)
            chunk = Chunk(
                id=block.id,
                file=block.id,
                file_hash=digest,
                section=block.slide_type,
                text=block.text(),
            )
            index.replace_file(block.id, digest, [chunk], [vector])
    index.save()
    return index


def search_blocks(
    root: Path,
    query: str,
    llm: LLMClient,
    embed_model: str,
    *,
    slide_type: str | None = None,
    tags: Sequence[str] = (),
    k: int = 5,
    min_score: float = -1.0,
    include_flagged: bool = True,
) -> list[tuple[Block, float]]:
    """Blocks most similar to ``query`` (embedding score + 0.05 per matching tag)."""
    blocks = [
        b
        for b in load_blocks(root)
        if (slide_type is None or b.slide_type == slide_type)
        and (include_flagged or not b.needs_review)
    ]
    if not blocks or not query.strip():
        return [(b, 0.0) for b in blocks[:k]]
    index = sync_index(root, load_blocks(root), llm, embed_model)
    [vector] = llm.embed([query])
    scores = {h.chunk.id: h.score for h in index.search(vector, len(index))}
    wanted_tags = {t.lower() for t in tags} | set(re.findall(r"[a-z0-9]+", query.lower()))
    ranked = sorted(
        ((b, scores.get(b.id, -1.0) + 0.05 * len(wanted_tags & set(b.tags))) for b in blocks),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [(b, s) for b, s in ranked if s >= min_score][:k]
