"""Render ``deck.json`` onto the user's template with python-pptx. No LLM is involved.

Each slide goes into the layout and placeholders named in ``config/layout_map.yaml``. Text over
its limit is truncated at a word boundary and flagged; unfilled placeholders are removed so no
"Click to add text" prompts remain; the architecture slide is drawn as layered boxes. Output is
versioned (``<name>-v<N>.pptx``) and never overwrites, and every run returns a QA report.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.presentation import Presentation as PresentationType
from pptx.slide import Slide as PptxSlide
from pptx.util import Emu, Inches, Pt

from studio.config import LayoutMapConfig, LayoutSpec, Limits
from studio.deck.schemas import (
    ArchitectureSlide,
    BeforeAfterSlide,
    Deck,
    SlideBase,
    TitleSlide,
    list_fields,
)
from studio.render.inspect_template import TemplateError, open_template
from studio.render.sample_template import ACCENT, ACCENT_LIGHT, INK, LINE, SURFACE

ELLIPSIS = "…"


@dataclass
class QaReport:
    """What the render did, and anything a human should look at."""

    slide_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)
    empty_placeholders: list[str] = field(default_factory=list)
    missing_provenance: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when there are no errors (warnings are allowed)."""
        return not self.errors

    def to_markdown(self, path: Path | None = None) -> str:
        """Readable QA summary for chat or the terminal."""
        status = "✅ no errors" if self.ok else f"❌ {len(self.errors)} errors"
        lines = [f"## Render QA — {self.slide_count} slides, {status}"]
        if path:
            lines.append(f"File: {path}")
        for title, items in (
            ("Errors", self.errors),
            ("Truncated to fit", self.truncated),
            ("Empty placeholders", self.empty_placeholders),
            ("Missing provenance (no sources)", self.missing_provenance),
            ("Warnings", self.warnings),
        ):
            if items:
                lines += ["", f"### {title}", *(f"- {item}" for item in items)]
        lines += [
            "",
            "Next: open the PPTX and review it; `/edit <slide_id> …` then `/render` again.",
        ]
        return "\n".join(lines)


@dataclass
class RenderReport:
    """Result of a render: the written file (None if nothing was written) and the QA report."""

    path: Path | None
    qa: QaReport


# --- helpers --------------------------------------------------------------------------------


def truncate(text: str, limit: int) -> str:
    """Cut ``text`` to at most ``limit`` chars at a word boundary, ending with an ellipsis."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[: max(limit - 1, 1)]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-—") + ELLIPSIS


def next_version_path(out_dir: Path, name: str, suffix: str = ".pptx") -> Path:
    """``<out_dir>/<name>-v<N><suffix>`` for the first N not yet used."""
    out_dir.mkdir(parents=True, exist_ok=True)
    version = 1
    while (path := out_dir / f"{name}-v{version}{suffix}").exists():
        version += 1
    return path


def _remove_existing_slides(prs: PresentationType) -> int:
    sld_id_lst = prs.slides._sldIdLst
    removed = 0
    for sld_id in list(sld_id_lst):
        prs.part.drop_rel(sld_id.rId)
        sld_id_lst.remove(sld_id)
        removed += 1
    return removed


def _find_layout(prs: PresentationType, name: str):
    for layout in prs.slide_layouts:
        if layout.name.strip().lower() == name.strip().lower():
            return layout
    return None


def _find_placeholder(slide: PptxSlide, ref: int | str):
    for ph in slide.placeholders:
        if isinstance(ref, int) and ph.placeholder_format.idx == ref:
            return ph
        if isinstance(ref, str) and ph.name.strip().lower() == ref.strip().lower():
            return ph
    return None


def _set_paragraphs(shape, items: Sequence[str]) -> None:
    """Replace a placeholder's text with one paragraph per item, keeping layout formatting."""
    frame = shape.text_frame
    frame.text = items[0] if items else ""
    for item in items[1:]:
        frame.add_paragraph().text = item


# --- per-slide content ----------------------------------------------------------------------


def _slide_fields(slide: SlideBase, limits: Limits, qa: QaReport) -> dict[str, list[str]]:
    """Field name → paragraphs to place, after limits are enforced (and recorded in ``qa``)."""

    def fit(field_name: str, text: str, limit: int) -> str:
        out = truncate(text, limit)
        if out != text.strip():
            qa.truncated.append(f"{slide.id}.{field_name}: {len(text)} → {len(out)} chars")
        return out

    fields: dict[str, list[str]] = {"title": [fit("title", slide.title, limits.title)]}
    if isinstance(slide, TitleSlide):
        fields["subtitle"] = [fit("subtitle", slide.subtitle, limits.subtitle)]
    if isinstance(slide, BeforeAfterSlide):
        fields["before_title"] = [fit("before_title", slide.before_title, limits.title)]
        fields["after_title"] = [fit("after_title", slide.after_title, limits.title)]
    for name, items in list_fields(slide).items():
        if len(items) > limits.max_bullets:
            qa.warnings.append(
                f"{slide.id}.{name}: kept the first {limits.max_bullets} of {len(items)} items"
            )
            items = items[: limits.max_bullets]
        elif len(items) < limits.min_bullets:
            qa.warnings.append(
                f"{slide.id}.{name}: only {len(items)} items (expected {limits.min_bullets}+)"
            )
        fields[name] = [fit(f"{name}[{n}]", t, limits.bullet) for n, t in enumerate(items, 1)]
    return {k: [v for v in vals if v] for k, vals in fields.items()}


def _draw_architecture(
    pptx_slide: PptxSlide,
    slide: ArchitectureSlide,
    spec: LayoutSpec,
    prs: PresentationType,
    limits: Limits,
    qa: QaReport,
) -> int:
    """Draw layers as rows of boxes; return the number of boxes drawn."""
    if spec.diagram_area:
        area = spec.diagram_area
        left, top = Inches(area.left), Inches(area.top)
        width, height = Inches(area.width), Inches(area.height)
    else:  # below the title band, inside 0.5" margins
        left, top = Inches(0.5), Inches(1.6)
        width, height = prs.slide_width - Inches(1.0), prs.slide_height - Inches(2.2)

    layers = slide.layers[: limits.max_layers]
    if len(slide.layers) > len(layers):
        qa.warnings.append(
            f"{slide.id}: kept the first {len(layers)} of {len(slide.layers)} layers"
        )
    if not layers:
        qa.errors.append(f"{slide.id}: architecture slide has no layers")
        return 0

    gap = Inches(0.12)
    row_h = Emu(int((height - gap * (len(layers) - 1)) / len(layers)))
    label_w = Emu(int(width * 0.22))
    font = Pt(14 if len(layers) <= 3 else 12 if len(layers) <= 5 else 10)
    boxes = 0

    def box(x, y, w, h, text: str, fill: RGBColor, color: RGBColor, bold: bool = False) -> None:
        shape = pptx_slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
        shape.line.color.rgb = LINE
        shape.shadow.inherit = False
        frame = shape.text_frame
        frame.word_wrap = True
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        para = frame.paragraphs[0]
        para.alignment = PP_ALIGN.CENTER
        run = para.add_run()
        run.text = text
        run.font.size = font
        run.font.bold = bold
        run.font.color.rgb = color

    for n, layer in enumerate(layers, start=1):
        y = Emu(int(top + (row_h + gap) * (n - 1)))
        name = truncate(layer.name, limits.layer)
        if name != layer.name.strip():
            qa.truncated.append(f"{slide.id}.layers[{n}].name")
        box(left, y, label_w, row_h, name, ACCENT, RGBColor(0xFF, 0xFF, 0xFF), bold=True)
        boxes += 1
        comps = layer.components[: limits.max_components]
        if len(layer.components) > len(comps):
            qa.warnings.append(f"{slide.id}.layers[{n}]: kept {len(comps)} components")
        if not comps:
            continue
        x0 = left + label_w + gap
        avail = width - label_w - gap
        comp_w = Emu(int((avail - gap * (len(comps) - 1)) / len(comps)))
        for m, comp in enumerate(comps):
            text = truncate(comp, limits.component)
            if text != comp.strip():
                qa.truncated.append(f"{slide.id}.layers[{n}].components[{m + 1}]")
            fill = ACCENT_LIGHT if m % 2 == 0 else SURFACE
            box(Emu(int(x0 + (comp_w + gap) * m)), y, comp_w, row_h, text, fill, INK)
            boxes += 1
    return boxes


def _render_slide(
    prs: PresentationType, slide: SlideBase, cfg: LayoutMapConfig, qa: QaReport
) -> None:
    spec = cfg.layouts.get(slide.slide_type)
    if spec is None:
        qa.errors.append(
            f"{slide.id}: no layout mapped for slide type '{slide.slide_type}' in layout_map.yaml"
        )
        return
    layout = _find_layout(prs, spec.layout)
    if layout is None:
        names = ", ".join(f"'{lay.name}'" for lay in prs.slide_layouts)
        qa.errors.append(
            f"{slide.id}: layout '{spec.layout}' isn't in the template. Available: {names}"
        )
        return

    limits = cfg.limits_for(slide.slide_type)
    pptx_slide = prs.slides.add_slide(layout)
    used: set[int] = set()
    for name, paragraphs in _slide_fields(slide, limits, qa).items():
        ref = spec.placeholders.get(name)
        if ref is None:
            if paragraphs:
                qa.warnings.append(f"{slide.id}.{name}: no placeholder mapped; content not shown")
            continue
        shape = _find_placeholder(pptx_slide, ref)
        if shape is None:
            qa.errors.append(
                f"{slide.id}.{name}: placeholder {ref!r} not found on layout '{layout.name}'"
            )
            continue
        if not paragraphs:
            qa.empty_placeholders.append(f"{slide.id}.{name}")
            continue
        _set_paragraphs(shape, paragraphs)
        used.add(shape.shape_id)

    # Remove anything left unfilled so no "Click to add text" prompts remain.
    for ph in list(pptx_slide.placeholders):
        if ph.shape_id not in used:
            ph._element.getparent().remove(ph._element)

    if isinstance(slide, ArchitectureSlide):
        _draw_architecture(pptx_slide, slide, spec, prs, limits, qa)

    qa.warnings.extend(f"{slide.id}: review — {flag}" for flag in slide.review)
    notes = truncate(slide.speaker_notes, limits.notes) if slide.speaker_notes else ""
    if len(slide.speaker_notes.strip()) > limits.notes:
        qa.truncated.append(f"{slide.id}.speaker_notes")
    if slide.sources:
        notes = f"{notes}\n\nSources: {'; '.join(slide.sources)}".strip()
    elif not isinstance(slide, TitleSlide):
        qa.missing_provenance.append(slide.id)
    if notes:
        pptx_slide.notes_slide.notes_text_frame.text = notes


def render(
    deck: Deck,
    cfg: LayoutMapConfig,
    template_path: Path,
    out_dir: Path,
    name: str,
) -> RenderReport:
    """Render ``deck`` on ``template_path`` into ``out_dir/<name>-v<N>.pptx``.

    Returns the path (None if the template could not be used) and a QA report. Slides with a
    mapping error are skipped and reported; everything else is still rendered.
    """
    qa = QaReport()
    try:
        prs = open_template(template_path)
    except TemplateError as exc:
        qa.errors.append(str(exc))
        return RenderReport(None, qa)
    if cfg.remove_existing_slides:
        _remove_existing_slides(prs)
    if not deck.slides:
        qa.errors.append("deck.json has no slides. Run `/deck` first.")
    for slide in deck.slides:
        _render_slide(prs, slide, cfg, qa)
    qa.slide_count = len(prs.slides)
    path = next_version_path(out_dir, name)
    prs.save(str(path))
    return RenderReport(path, qa)
