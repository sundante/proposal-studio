"""Generate the neutral, original sample template (``templates/sample/proposal-sample.pptx``).

Built in code from python-pptx's generic default template: widescreen 16:9, a light palette,
one accent bar and a neutral footer. It contains no brand assets. Two placeholder slides are
included so the renderer's "remove existing slides" path is exercised.
"""

from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

INK = RGBColor(0x1F, 0x2A, 0x37)  # dark slate text
MUTED = RGBColor(0x5B, 0x67, 0x75)
ACCENT = RGBColor(0x0F, 0x76, 0x6E)  # teal
ACCENT_LIGHT = RGBColor(0xE6, 0xF4, 0xF1)
SURFACE = RGBColor(0xF5, 0xF7, 0xFA)
LINE = RGBColor(0xC9, 0xD2, 0xDC)

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)


def _scale_x(shapes, factor: float) -> None:
    """Widen shapes that set their own position; inherited placeholders follow the master."""
    for shape in shapes:
        sp_pr = shape._element.find(qn("p:spPr"))
        if sp_pr is None or sp_pr.find(qn("a:xfrm")) is None:
            continue
        shape.left = Emu(int(shape.left * factor))
        shape.width = Emu(int(shape.width * factor))


def _set_style_color(master, style_tag: str, color: RGBColor, levels: int) -> None:
    """Give a master text style (title/body) a solid color for its first ``levels`` levels."""
    tx_styles = master._element.find(qn("p:txStyles"))
    style = tx_styles.find(qn(style_tag)) if tx_styles is not None else None
    if style is None:
        return
    for lvl in range(1, levels + 1):
        ppr = style.find(qn(f"a:lvl{lvl}pPr"))
        rpr = ppr.find(qn("a:defRPr")) if ppr is not None else None
        if rpr is None:
            continue
        for old in rpr.findall(qn("a:solidFill")):
            rpr.remove(old)
        fill = etree.SubElement(rpr, qn("a:solidFill"))
        etree.SubElement(fill, qn("a:srgbClr"), val=str(color))
        rpr.insert(0, fill)  # schema order: fill comes before latin/ea/cs fonts


def build_sample_template(path: Path) -> Path:
    """Write the sample template to ``path`` and return it."""
    prs = Presentation()
    factor = SLIDE_W / prs.slide_width
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    master = prs.slide_master
    _scale_x(master.shapes, factor)
    for layout in prs.slide_layouts:
        _scale_x(layout.shapes, factor)
    _set_style_color(master, "p:titleStyle", INK, 1)
    _set_style_color(master, "p:bodyStyle", INK, 3)

    # Decorations are drawn on a scratch slide, then moved onto the master.
    scratch = prs.slides.add_slide(prs.slide_layouts[6])
    bar = scratch.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, Inches(0.12))
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    footer = scratch.shapes.add_textbox(Inches(0.5), Inches(7.05), Inches(6), Inches(0.3))
    run = footer.text_frame.paragraphs[0].add_run()
    run.text = "Proposal Studio sample template"
    run.font.size = Pt(10)
    run.font.color.rgb = MUTED
    sp_tree = master.shapes._spTree
    for shape in (bar, footer):
        sp_tree.insert(2, copy.deepcopy(shape._element))  # after nvGrpSpPr/grpSpPr: behind
    sldIdLst = prs.slides._sldIdLst
    scratch_id = sldIdLst[-1]
    prs.part.drop_rel(scratch_id.rId)
    sldIdLst.remove(scratch_id)

    for text in ("Sample slide — replaced at render time", "Instructions slide — removed"):
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = text
        slide.placeholders[1].text_frame.text = "Your own template's example slides go away too."

    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return path
