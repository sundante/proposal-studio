"""Outline: which storyline slides go in the deck, and why (``outline.json``).

``config/storyline.yaml`` is a fixed spine. Required slides are always in. Optional slides use
``include_if`` rules over the digest (any matching rule includes the slide):

- ``<field> contains <text>``   e.g. ``compliance contains HITRUST`` (case-insensitive)
- ``<field> not empty``         e.g. ``risks_and_red_flags not empty``
- ``<field> count >= <n>``      e.g. ``requirements count >= 10``

Optional slides without rules are included by default. ``/toggle`` overrides persist across
rebuilds.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from studio.config import StorylineConfig
from studio.digest import Digest

OUTLINE_FILE = "outline.json"
_RULE = re.compile(
    r"^\s*(?P<field>[a-z_]+)\s+(?:(?P<contains>contains)\s+(?P<text>.+?)"
    r"|(?P<notempty>not empty)|count\s*>=\s*(?P<count>\d+))\s*$",
    re.I,
)


class OutlineError(ValueError):
    """Invalid storyline rule or outline operation. User-facing."""


class OutlineSlide(BaseModel):
    """One storyline slide and whether it's in the deck."""

    id: str
    slide_type: str
    included: bool
    required: bool
    reason: str
    max_items: int | None = None
    toggled: bool = False


class Outline(BaseModel):
    """The deck plan written to ``outline.json``."""

    opportunity: str
    slides: list[OutlineSlide] = Field(default_factory=list)

    def included(self) -> list[OutlineSlide]:
        """Slides that will be written, in order."""
        return [s for s in self.slides if s.included]


@dataclass(frozen=True)
class Rule:
    """A parsed ``include_if`` rule."""

    field: str
    op: str  # contains | not_empty | count_ge
    value: str = ""

    def __str__(self) -> str:
        if self.op == "contains":
            return f"{self.field} contains {self.value}"
        if self.op == "not_empty":
            return f"{self.field} not empty"
        return f"{self.field} count >= {self.value}"


def parse_rule(text: str) -> Rule:
    """Parse one ``include_if`` rule, or raise :class:`OutlineError` naming the valid forms."""
    match = _RULE.match(text)
    if not match or match.group("field") not in Digest.model_fields:
        raise OutlineError(
            f"Invalid include_if rule '{text}'. Use '<field> contains <text>', '<field> not "
            f"empty' or '<field> count >= N', with a digest field such as compliance."
        )
    field_name = match.group("field")
    if match.group("contains"):
        return Rule(field_name, "contains", match.group("text").strip())
    if match.group("notempty"):
        return Rule(field_name, "not_empty")
    return Rule(field_name, "count_ge", match.group("count"))


def _items(digest: Digest, field_name: str) -> list[Any]:
    value = getattr(digest, field_name)
    if isinstance(value, BaseModel):  # opportunity: treat set fields as items
        return [v for v in value.model_dump().values() if v]
    return list(value)


def _item_text(item: Any) -> str:
    return (
        json.dumps(item.model_dump(), ensure_ascii=False)
        if isinstance(item, BaseModel)
        else str(item)
    )


def _item_cite(item: Any) -> str:
    cites = getattr(item, "cite", None) or getattr(item, "evidence", None) or []
    return "".join(str(c) for c in cites[:1])


def evaluate(rule: Rule, digest: Digest) -> tuple[bool, str]:
    """Whether ``rule`` holds for ``digest``, and a short explanation with a citation."""
    items = _items(digest, rule.field)
    if rule.op == "contains":
        needle = rule.value.lower()
        for item in items:
            if needle in _item_text(item).lower():
                cite = _item_cite(item)
                return True, f"rule matched: {rule}" + (f" {cite}" if cite else "")
        return False, f"no match for: {rule}"
    if rule.op == "not_empty":
        return (True, f"rule matched: {rule}") if items else (False, f"empty: {rule.field}")
    ok = len(items) >= int(rule.value)
    return ok, f"{'rule matched' if ok else 'not met'}: {rule} ({len(items)})"


def build_outline(
    storyline: StorylineConfig, digest: Digest, opp_id: str, previous: Outline | None = None
) -> Outline:
    """Decide which slides are in, re-applying earlier ``/toggle`` choices from ``previous``."""
    toggles = {s.id: s for s in (previous.slides if previous else []) if s.toggled}
    slides = []
    for spec in storyline.slides:
        rules = [parse_rule(r) for r in spec.include_if]
        if spec.required:
            included, reason = True, "required"
        elif rules:
            results = [evaluate(rule, digest) for rule in rules]
            hits = [why for ok, why in results if ok]
            included = bool(hits)
            reason = (
                "; ".join(hits)
                if hits
                else "no rule matched (" + "; ".join(w for _, w in results) + ")"
            )
        else:
            included, reason = True, "optional (no rule) — `/toggle` to remove"
        slide = OutlineSlide(
            id=spec.id,
            slide_type=spec.slide_type,
            included=included,
            required=spec.required,
            reason=reason,
            max_items=spec.max_items,
        )
        if spec.id in toggles and not spec.required:
            prior = toggles[spec.id]
            slide = slide.model_copy(
                update={"included": prior.included, "toggled": True, "reason": prior.reason}
            )
        slides.append(slide)
    return Outline(opportunity=opp_id, slides=slides)


def toggle(outline: Outline, slide_id: str, on: bool) -> Outline:
    """Turn an optional slide on or off (required slides can't be turned off)."""
    for n, slide in enumerate(outline.slides):
        if slide.id != slide_id:
            continue
        if slide.required and not on:
            raise OutlineError(f"'{slide_id}' is a required slide and can't be turned off.")
        outline.slides[n] = slide.model_copy(
            update={
                "included": on,
                "toggled": True,
                "reason": f"toggled {'on' if on else 'off'} by you",
            }
        )
        return outline
    ids = ", ".join(s.id for s in outline.slides)
    raise OutlineError(f"No slide '{slide_id}' in the outline. Slides: {ids}")


def load_outline(opp_dir: Path) -> Outline | None:
    """The saved outline, or None."""
    path = opp_dir / OUTLINE_FILE
    return Outline.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def save_outline(opp_dir: Path, outline: Outline) -> Path:
    """Write ``outline.json``."""
    path = opp_dir / OUTLINE_FILE
    path.write_text(outline.model_dump_json(indent=2), encoding="utf-8")
    return path


def render_outline(outline: Outline) -> str:
    """Readable outline for chat or the terminal."""
    lines = [f"## Outline — {len(outline.included())} of {len(outline.slides)} slides"]
    for n, s in enumerate(outline.slides, start=1):
        mark = "✅" if s.included else "⬜"
        lines.append(f"{n}. {mark} **{s.id}** — {s.reason}")
    lines += ["", "Next: `/deck` (or `/toggle <slide_id> on|off`)"]
    return "\n".join(lines)
