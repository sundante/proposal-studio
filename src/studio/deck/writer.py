"""Deck writer: tailor vetted blocks to the RFP digest, one slide per LLM call (``deck.json``).

For each slide in the outline: retrieve 2–4 blocks of that slide type, give the worker the
blocks and the slide's digest facts (numbered), and ask for that slide's content. Python then
checks limits (one "shorten" retry, then safe truncation + flag), maps cited block/fact numbers
to provenance, and flags numbers or certifications that appear in neither the blocks nor the
RFP. Slides about us with no vetted blocks become visible skeletons — never invented.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, create_model

from studio.blocks import DATE_RE, MONEY_RE, Block, load_blocks, search_blocks
from studio.config import Limits, StudioConfig
from studio.deck.schemas import (
    Deck,
    SlideBase,
    list_fields,
    model_for,
    slide_model,
)
from studio.deck.storyline import OutlineSlide, build_outline, load_outline, save_outline
from studio.digest import Digest, load_digest
from studio.llm import LLMClient, Message
from studio.render.renderer import truncate

StatusFn = Callable[[str], None]
DECK_FILE = "deck.json"
CLIENT_TYPES = {"understanding", "before_after"}  # may be written from the RFP alone
CERTIFICATIONS = (
    "HITRUST",
    "SOC 2",
    "SOC2",
    "ISO 27001",
    "ISO 27701",
    "ISO 42001",
    "FedRAMP",
    "PCI DSS",
    "HIPAA",
    "GDPR",
    "NIST",
    "CMS-0057",
)

DESCRIPTIONS = {
    "understanding": "our understanding of the client's business and technical challenges",
    "before_after": "current state (before) versus the future state with us (after)",
    "solution_architecture": "AI solution architecture as 3-5 layers, each with components",
    "ai_enablement": "the AI enablement advantages we bring",
    "platform": "complete AI platform: development, MLOps/LLMOps, observability, governance",
    "governance": "responsible AI, security and HIPAA/HITRUST alignment",
    "maturity": "maturing the client on AI: 3-5 roadmap stages",
    "practice_leadership": "AI as a practice: leadership and insights",
    "why_us": "our differentiators",
    "next_steps": "engagement plan / timeline: 3-5 steps with when and what",
}
FACT_FIELDS = {
    "understanding": ("business_problems", "technical_problems"),
    "before_after": ("current_state", "desired_outcomes"),
    "solution_architecture": ("technical_problems", "systems_mentioned", "requirements"),
    "ai_enablement": ("desired_outcomes", "business_problems"),
    "platform": ("requirements", "technical_problems"),
    "governance": ("compliance", "risks_and_red_flags"),
    "maturity": ("desired_outcomes", "current_state"),
    "practice_leadership": ("evaluation_criteria", "desired_outcomes"),
    "why_us": ("evaluation_criteria", "risks_and_red_flags"),
    "next_steps": ("opportunity", "requirements", "open_questions"),
}
MAX_FACTS = 12


class DeckError(ValueError):
    """The deck could not be written. User-facing."""


@dataclass(frozen=True)
class Fact:
    """One digest fact offered to the writer, with its citation."""

    text: str
    cite: str = ""


def facts_for(slide_type: str, digest: Digest) -> list[Fact]:
    """The digest facts relevant to a slide type, mandatory requirements first."""
    facts: list[Fact] = []
    for name in FACT_FIELDS.get(slide_type, ()):
        if name == "opportunity":
            o = digest.opportunity
            facts += [Fact(f"Due date: {o.due_date}")] if o.due_date else []
            facts += [Fact(f"Limits: {o.page_or_slide_limits}")] if o.page_or_slide_limits else []
            continue
        for item in getattr(digest, name):
            if name in ("business_problems", "technical_problems"):
                facts.append(Fact(item.statement, "".join(map(str, item.evidence[:1]))))
            elif name == "current_state":
                facts.append(Fact(f"Today: {item.item}", "".join(map(str, item.evidence[:1]))))
            elif name == "desired_outcomes":
                facts.append(Fact(f"Wanted: {item.item}", "".join(map(str, item.evidence[:1]))))
            elif name == "requirements":
                flag = "mandatory" if item.mandatory else "optional"
                facts.append(
                    Fact(f"{item.id} ({flag}): {item.text}", "".join(map(str, item.cite[:1])))
                )
            elif name == "evaluation_criteria":
                weight = f" ({item.weight})" if item.weight else ""
                facts.append(
                    Fact(f"Scored on: {item.criterion}{weight}", "".join(map(str, item.cite[:1])))
                )
            elif name == "compliance":
                facts.append(
                    Fact(f"{item.framework}: {item.detail}", "".join(map(str, item.cite[:1])))
                )
            elif name == "systems_mentioned":
                facts.append(
                    Fact(f"System: {item.name}" + (f" — {item.role}" if item.role else ""))
                )
            elif name == "risks_and_red_flags":
                facts.append(Fact(f"Risk: {item.item}", "".join(map(str, item.cite[:1]))))
            elif name == "open_questions":
                facts.append(Fact(f"Open question: {item}"))
    if any("mandatory" in f.text for f in facts):
        facts.sort(key=lambda f: "(optional)" in f.text)
    return facts[:MAX_FACTS]


def writer_schema(slide_type: str, limits: Limits) -> type[BaseModel]:
    """LLM schema: unconstrained slide content plus the block/fact numbers used."""
    base = slide_model(slide_type, limits, enforce=False)
    return create_model(
        f"Write{base.__name__}",
        __base__=base,
        used_blocks=(list[int], Field(default_factory=list)),
        used_facts=(list[int], Field(default_factory=list)),
    )


_SYSTEM = """You write one slide of a proposal deck for a healthcare AI engagement.
Tailor the vetted blocks to this client's situation described by the RFP facts.
Rules:
- Claims about us must come from the vetted blocks. Do not invent metrics, client names,
  customer references or certifications.
- Use the RFP facts to make it specific to the client; replace {{client}} with the client name.
- Never fill a {{date}} or {{amount}} placeholder from a block with an unrelated RFP value;
  drop that part of the sentence instead.
- Respect the limits: short, concrete phrases; no trailing periods on bullets.
- used_blocks: the numbers of the blocks you drew on. used_facts: the numbers of the facts.
- speaker_notes: 2-4 sentences for the presenter."""


def _limits_text(slide_type: str, limits: Limits) -> str:
    items = f"{limits.min_bullets}-{limits.max_bullets} items of at most {limits.bullet} characters"
    if slide_type == "solution_architecture":
        items = (
            f"2-{limits.max_layers} layers (name at most {limits.layer} chars), each with 1-"
            f"{limits.max_components} components of at most {limits.component} characters"
        )
    return f"title at most {limits.title} characters; {items}"


CLIENT_RULE = (
    "This slide describes the client: every statement about the client must come from the RFP "
    "facts. Use the blocks only for structure and phrasing, never for facts about the client.\n"
)
TITLES = {
    "solution_architecture": "Solution architecture",
    "ai_enablement": "AI enablement",
    "platform": "A complete AI platform",
    "governance": "Responsible AI and compliance",
    "maturity": "Maturing on AI",
    "practice_leadership": "AI practice leadership",
    "why_us": "Why us",
    "next_steps": "Next steps",
}


def build_messages(
    slide: OutlineSlide,
    client: str,
    blocks: Sequence[Block],
    facts: Sequence[Fact],
    limits: Limits,
    extra: str = "",
) -> list[Message]:
    """Prompt for one slide."""
    block_text = (
        "\n\n".join(f"[B{n}] {b.text()}" for n, b in enumerate(blocks, start=1)) or "(none)"
    )
    fact_text = (
        "\n".join(f"[{n}] {f.text} {f.cite}".rstrip() for n, f in enumerate(facts, start=1))
        or "(none)"
    )
    user = (
        f"Client: {client}\nSlide: {slide.slide_type} — {DESCRIPTIONS.get(slide.slide_type, '')}\n"
        f"Limits: {_limits_text(slide.slide_type, limits)}\n\n"
        f"Vetted blocks:\n{block_text}\n\nRFP facts:\n{fact_text}\n"
        f"{CLIENT_RULE if slide.slide_type in CLIENT_TYPES else ''}{extra}\nWrite the slide JSON."
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


# --- validation -----------------------------------------------------------------------------


def _fit(content: dict[str, Any], limits: Limits, flags: list[str]) -> dict[str, Any]:
    """Truncate/trim content to the limits, recording what changed in ``flags``."""

    def cut(path: str, text: str, limit: int) -> str:
        out = truncate(text, limit)
        if out != text.strip():
            flags.append(f"{path} shortened to fit {limit} chars")
        return out

    def trim(path: str, items: list[Any], limit: int) -> list[Any]:
        if len(items) > limit:
            flags.append(f"{path}: kept {limit} of {len(items)}")
        return items[:limit]

    detail = max(limits.bullet - limits.layer - 3, 20)
    out = dict(content)
    for key, limit in (("title", limits.title), ("subtitle", limits.subtitle)):
        if isinstance(out.get(key), str):
            out[key] = cut(key, out[key], limit)
    for key in ("bullets", "before", "after"):
        if isinstance(out.get(key), list):
            out[key] = [
                cut(f"{key}[{n}]", t, limits.bullet)
                for n, t in enumerate(trim(key, out[key], limits.max_bullets), 1)
            ]
    if isinstance(out.get("layers"), list):
        layers = []
        for n, layer in enumerate(trim("layers", out["layers"], limits.max_layers), start=1):
            comps = trim(f"layers[{n}]", list(layer.get("components", [])), limits.max_components)
            layers.append(
                {
                    "name": cut(f"layers[{n}].name", layer.get("name", ""), limits.layer),
                    "components": [
                        cut(f"layers[{n}].components", c, limits.component) for c in comps
                    ],
                }
            )
        out["layers"] = layers
    for key, a, b in (("stages", "name", "description"), ("steps", "when", "what")):
        if isinstance(out.get(key), list):
            out[key] = [
                {
                    a: cut(f"{key}.{a}", item.get(a, ""), limits.layer),
                    b: cut(f"{key}.{b}", item.get(b, ""), detail),
                }
                for item in trim(key, out[key], limits.max_bullets)
            ]
    return out


def _over_limits(content: dict[str, Any], slide_type: str, limits: Limits) -> list[str]:
    try:
        slide_model(slide_type, limits).model_validate(content)
        return []
    except ValidationError as exc:
        return [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in exc.errors()
            if e["type"] in ("string_too_long", "too_long")
        ]


def _numbers(text: str) -> set[str]:
    return {m.group(0).rstrip(".,") for m in re.finditer(r"\b\d[\d,.]*%?", text)}


def invention_flags(output: str, allowed: str) -> list[str]:
    """Numbers or certifications in ``output`` that don't appear in ``allowed`` source text."""
    flags = []
    numbers = sorted(_numbers(output) - _numbers(allowed))
    if numbers:
        flags.append(f"figure(s) not found in the blocks or RFP: {', '.join(numbers)}")
    low_allowed = allowed.lower()
    certs = [
        c
        for c in CERTIFICATIONS
        if re.search(rf"\b{re.escape(c)}\b", output, re.I) and c.lower() not in low_allowed
    ]
    if certs:
        flags.append(f"certification(s) not in the blocks or RFP: {', '.join(certs)}")
    return flags


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}


def unsupported_client_claims(items: Sequence[str], facts: Sequence[Fact]) -> list[str]:
    """Items on a client-facing slide that share almost no words with any RFP fact."""
    fact_words = [_words(f.text) for f in facts]
    flags = []
    for item in items:
        words = _words(item)
        best = max((len(words & fw) / max(len(words), 1) for fw in fact_words), default=0.0)
        if words and best < 0.3:
            flags.append(f"not supported by the RFP facts: '{item}'")
    return flags


def filled_placeholder_flags(output: str, blocks: Sequence[Block]) -> list[str]:
    """Dates/amounts in the output where a used block only had a {{date}}/{{amount}} slot."""
    texts = " ".join(b.text() for b in blocks)
    flags = []
    for slot, pattern in (("{{date}}", DATE_RE), ("{{amount}}", MONEY_RE)):
        if slot in texts:
            found = sorted({m.group(0) for m in pattern.finditer(output)})
            if found:
                flags.append(
                    f"a block's {slot} may have been filled with {', '.join(found)}: check"
                )
    return flags


@dataclass
class _Context:
    root: Path
    cfg: StudioConfig
    llm: LLMClient
    digest: Digest
    client: str
    status: StatusFn


def _complete(
    ctx: _Context,
    slide: OutlineSlide,
    blocks: Sequence[Block],
    facts: Sequence[Fact],
    messages: list[Message],
) -> SlideBase:
    """Run the LLM for one slide and apply every Python-side check."""
    limits = ctx.cfg.layout_map.limits_for(slide.slide_type)
    if slide.max_items:
        limits = limits.model_copy(update={"max_bullets": min(limits.max_bullets, slide.max_items)})
    schema = writer_schema(slide.slide_type, limits)
    result = ctx.llm.generate_structured("worker", messages, schema)
    content = result.model_dump(exclude={"used_blocks", "used_facts"})
    over = _over_limits(content, slide.slide_type, limits)
    if over:  # one automatic shorten retry
        retry = [
            *messages,
            {"role": "assistant", "content": result.model_dump_json()},
            {
                "role": "user",
                "content": "Too long: "
                + "; ".join(over)
                + ". Shorten those fields; keep the meaning.",
            },
        ]
        result = ctx.llm.generate_structured("worker", retry, schema)
        content = result.model_dump(exclude={"used_blocks", "used_facts"})

    review: list[str] = []
    escaped = json.dumps(ctx.client)[1:-1]
    content = json.loads(json.dumps(content).replace("{{client}}", escaped))
    content = _fit(content, limits, review)

    used_blocks = [
        blocks[n - 1] for n in dict.fromkeys(result.used_blocks) if 1 <= n <= len(blocks)
    ]
    used_facts = [facts[n - 1] for n in dict.fromkeys(result.used_facts) if 1 <= n <= len(facts)]
    bad_refs = [n for n in result.used_blocks if not 1 <= n <= len(blocks)] + [
        n for n in result.used_facts if not 1 <= n <= len(facts)
    ]
    if bad_refs:
        review.append(f"ignored unknown block/fact references: {bad_refs}")
    used_blocks = used_blocks or list(blocks)
    used_facts = used_facts or list(facts)
    sources = [f"block:{b.id}" for b in used_blocks] + list(
        dict.fromkeys(f.cite for f in used_facts if f.cite)
    )

    allowed = " ".join([ctx.client, *(b.text() for b in blocks), *(f.text for f in facts)])
    shown = json.dumps(
        {k: v for k, v in content.items() if k != "speaker_notes"}, ensure_ascii=False
    )
    review += invention_flags(shown, allowed)
    review += filled_placeholder_flags(shown, used_blocks)
    if not blocks:
        review.append("no vetted blocks: written from the RFP facts only")
    if any(b.needs_review for b in used_blocks):
        review.append("uses blocks still marked needs_review")

    built = model_for(slide.slide_type).model_validate(
        {
            **content,
            "id": slide.id,
            "slide_type": slide.slide_type,
            "sources": sources,
        }
    )
    if slide.slide_type in CLIENT_TYPES:
        items = [i for values in list_fields(built).values() for i in values]
        review += unsupported_client_claims(items, facts)
    return built.model_copy(update={"review": review})


def _skeleton(slide: OutlineSlide) -> SlideBase:
    note = f"Add content — no vetted blocks for {slide.slide_type}; run /harvest"
    content: dict[str, Any] = {"title": TITLES.get(slide.slide_type, slide.slide_type)}
    if slide.slide_type == "solution_architecture":
        content["layers"] = [{"name": "Add layers", "components": ["Run /harvest"]}]
    elif slide.slide_type == "maturity":
        content["stages"] = [{"name": "Add stages", "description": "Run /harvest"}]
    elif slide.slide_type == "next_steps":
        content["steps"] = [{"when": "Add steps", "what": "Run /harvest"}]
    else:
        content["bullets"] = [note]
    return model_for(slide.slide_type).model_validate(
        {**content, "id": slide.id, "slide_type": slide.slide_type, "review": [note]}
    )


def _title_slide(slide: OutlineSlide, digest: Digest, client: str, limits: Limits) -> SlideBase:
    o = digest.opportunity
    title = truncate(o.title or f"Proposal for {client}", limits.title)
    parts = [f"Proposal for {client}" if client else "", o.due_date or ""]
    return model_for("title").model_validate(
        {
            "id": slide.id,
            "slide_type": "title",
            "title": title,
            "subtitle": truncate(" · ".join(p for p in parts if p), limits.subtitle),
            "sources": ["digest:opportunity"],
        }
    )


def write_slide(ctx: _Context, slide: OutlineSlide) -> SlideBase:
    """Write one slide (title is deterministic; others tailor vetted blocks)."""
    limits = ctx.cfg.layout_map.limits_for(slide.slide_type)
    if slide.slide_type == "title":
        return _title_slide(slide, ctx.digest, ctx.client, limits)
    facts = facts_for(slide.slide_type, ctx.digest)
    query = " ".join(f.text for f in facts) or DESCRIPTIONS.get(slide.slide_type, slide.slide_type)
    hits = search_blocks(
        ctx.root,
        query,
        ctx.llm,
        ctx.cfg.models.roles["embed"].model,
        slide_type=slide.slide_type,
        k=ctx.cfg.deck.blocks_per_slide,
        min_score=ctx.cfg.deck.min_block_score,
        include_flagged=ctx.cfg.deck.include_flagged_blocks,
    )
    blocks = [b for b, _ in hits]
    if not blocks and slide.slide_type not in CLIENT_TYPES:
        return _skeleton(slide)
    messages = build_messages(slide, ctx.client, blocks, facts, limits)
    return _complete(ctx, slide, blocks, facts, messages)


# --- deck files -----------------------------------------------------------------------------


@dataclass
class DeckReport:
    """What a /deck or /edit run did."""

    deck: Deck
    path: Path
    written: list[str] = field(default_factory=list)
    flagged: dict[str, list[str]] = field(default_factory=dict)
    diff: str = ""


def load_deck(opp_dir: Path) -> Deck | None:
    """The saved deck, or None."""
    path = opp_dir / DECK_FILE
    return Deck.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def _save(opp_dir: Path, deck: Deck) -> Path:
    path = opp_dir / DECK_FILE
    if path.exists():
        history = opp_dir / "history"
        history.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        shutil.copy2(path, history / f"deck-{stamp}.json")
    path.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
    return path


def _context(
    opp_dir: Path, root: Path, llm: LLMClient, cfg: StudioConfig, status: StatusFn
) -> _Context:
    digest = load_digest(opp_dir)
    if digest is None:
        raise DeckError("No digest yet. Run `/digest` first.")
    return _Context(root, cfg, llm, digest, digest.opportunity.client or "the client", status)


def write_deck(
    opp_dir: Path,
    opp_id: str,
    root: Path,
    llm: LLMClient,
    cfg: StudioConfig,
    *,
    slide_id: str | None = None,
    on_status: StatusFn | None = None,
) -> DeckReport:
    """Write ``deck.json`` for every included slide, or regenerate only ``slide_id``."""
    status = on_status or (lambda _msg: None)
    ctx = _context(opp_dir, root, llm, cfg, status)
    outline = load_outline(opp_dir)
    if outline is None:
        outline = build_outline(cfg.storyline, ctx.digest, opp_id)
        save_outline(opp_dir, outline)
    included = outline.included()
    if slide_id and slide_id not in {s.id for s in included}:
        raise DeckError(
            f"'{slide_id}' isn't an included slide. Included: {', '.join(s.id for s in included)}"
        )
    existing = {s.id: s for s in (load_deck(opp_dir) or Deck(opportunity=opp_id)).slides}
    targets = [s for s in included if slide_id in (None, s.id)]

    report_written, slides = [], []
    for oslide in included:
        if oslide in targets:
            status(f"Writing slide {targets.index(oslide) + 1}/{len(targets)}: {oslide.id}…")
            slides.append(write_slide(ctx, oslide))
            report_written.append(oslide.id)
        elif oslide.id in existing:
            slides.append(existing[oslide.id])
    deck = Deck(
        opportunity=opp_id,
        client=ctx.digest.opportunity.client,
        generated=datetime.now(UTC).isoformat(timespec="seconds"),
        slides=slides,
    )
    path = _save(opp_dir, deck)
    flagged = {s.id: s.review for s in slides if s.review and s.id in report_written}
    return DeckReport(deck, path, report_written, flagged)


def slide_text(slide: SlideBase) -> list[str]:
    """A slide as readable lines (for diffs and chat)."""
    lines = [f"# {slide.title}"]
    if getattr(slide, "subtitle", ""):
        lines.append(slide.subtitle)  # type: ignore[attr-defined]
    for name, items in list_fields(slide).items():
        lines += [f"{name}:"] + [f"- {item}" for item in items]
    for layer in getattr(slide, "layers", []):
        lines.append(f"[{layer.name}] " + " | ".join(layer.components))
    if slide.speaker_notes:
        lines.append(f"notes: {slide.speaker_notes}")
    return lines


def edit_slide(
    opp_dir: Path,
    root: Path,
    llm: LLMClient,
    cfg: StudioConfig,
    slide_id: str,
    instruction: str,
    *,
    on_status: StatusFn | None = None,
) -> DeckReport:
    """Revise one slide following ``instruction``; returns the new deck and a before/after diff."""
    status = on_status or (lambda _msg: None)
    ctx = _context(opp_dir, root, llm, cfg, status)
    deck = load_deck(opp_dir)
    if deck is None:
        raise DeckError("No deck yet. Run `/deck` first.")
    index = next((n for n, s in enumerate(deck.slides) if s.id == slide_id), None)
    if index is None:
        raise DeckError(
            f"No slide '{slide_id}' in the deck. Slides: {', '.join(s.id for s in deck.slides)}"
        )
    before = deck.slides[index]
    if before.slide_type == "title":
        raise DeckError(
            "The title slide comes from the digest; edit the digest or deck.json instead."
        )

    by_id = {b.id: b for b in load_blocks(root)}
    blocks = [
        by_id[s.removeprefix("block:")] for s in before.sources if s.removeprefix("block:") in by_id
    ]
    facts = facts_for(before.slide_type, ctx.digest)
    oslide = OutlineSlide(
        id=before.id, slide_type=before.slide_type, included=True, required=False, reason="edit"
    )
    limits = cfg.layout_map.limits_for(before.slide_type)
    current = before.model_dump(exclude={"id", "slide_type", "sources", "review"})
    extra = (
        f"\nCurrent slide JSON:\n{json.dumps(current, ensure_ascii=False)}\n"
        f"Revise it following this instruction: {instruction}\n"
    )
    status(f"Revising {slide_id}…")
    after = _complete(
        ctx, oslide, blocks, facts, build_messages(oslide, ctx.client, blocks, facts, limits, extra)
    )
    deck.slides[index] = after
    path = _save(opp_dir, deck)
    diff = "\n".join(
        difflib.unified_diff(slide_text(before), slide_text(after), "before", "after", lineterm="")
    )
    return DeckReport(
        deck, path, [slide_id], {slide_id: after.review} if after.review else {}, diff
    )
