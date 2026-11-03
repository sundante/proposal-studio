"""Synthetic sample documents: a fictional "Acme Health Plan" RFP as PDF, DOCX, XLSX and PPTX.

Used by the tests and by ``studio smoke`` (end-to-end check on a real install). All content is
fictional. Usage: ``python -m studio.samples OUTDIR``.
"""

from __future__ import annotations

import sys
from pathlib import Path

CLIENT = "Acme Health Plan"
TITLE = f"{CLIENT} - Request for Proposal: Enterprise AI Platform"
DEADLINE = "Proposals are due by 5:00 PM ET on March 15, 2027 via the Acme procurement portal."

# (level, heading, paragraphs). Level 0 = document title.
SECTIONS: list[tuple[int, str, list[str]]] = [
    (0, TITLE, ["This document is synthetic sample content for testing."]),
    (
        1,
        "1 Introduction",
        [
            f"{CLIENT} is a fictional regional health plan serving members in three states. "
            "It seeks a partner to build an enterprise AI platform for care management.",
        ],
    ),
    (
        2,
        "1.1 Background",
        [
            "Care managers currently review claims and clinical notes manually in a legacy portal. "
            "Prior authorization turnaround averages nine days.",
        ],
    ),
    (
        1,
        "2 Submission Instructions",
        [
            DEADLINE,
            "Responses must not exceed 30 slides. Questions are accepted until February 1, 2027.",
        ],
    ),
    (
        1,
        "3 Scope of Work",
        [
            "The vendor will design, build and operate the platform for an initial term "
            "of two years.",
        ],
    ),
    (
        2,
        "3.1 Data Integration",
        [
            "The platform must ingest clinical data through FHIR R4 APIs from the Example "
            "EHR system and claims data from the existing data warehouse on a nightly schedule.",
        ],
    ),
    (
        2,
        "3.2 Compliance",
        [
            "All components must align with HIPAA and HITRUST CSF requirements. "
            "The vendor must support CMS-0057 interoperability rules for prior authorization.",
        ],
    ),
]

REQUIREMENTS = [
    ["ID", "Requirement", "Mandatory"],
    ["R-01", "Single sign-on with the Acme identity provider", "Yes"],
    ["R-02", "Model monitoring and drift alerts", "Yes"],
    ["R-03", "Self-service analytics workspace", "No"],
]

EVALUATION = (
    1,
    "5 Evaluation Criteria",
    [
        "Technical approach 40 percent, experience 30 percent, cost 30 percent.",
    ],
)


def make_pdf(path: Path) -> Path:
    """Three-page PDF: numbered headings in larger bold fonts and a ruled requirements table."""
    import pymupdf

    sizes = {0: 18, 1: 14, 2: 12}
    doc = pymupdf.open()
    pages = [SECTIONS[:4], SECTIONS[4:], []]
    for content in pages:
        page = doc.new_page(width=612, height=792)
        y = 72.0
        for level, heading, paras in content:
            page.insert_text((72, y), heading, fontsize=sizes[level], fontname="hebo")
            y += sizes[level] + 10
            for para in paras:
                rect = pymupdf.Rect(72, y, 540, y + 200)
                spare = page.insert_textbox(rect, para, fontsize=10, fontname="helv")
                y += 200 - spare + 10
            y += 6
    # Page 3: requirements table + evaluation criteria.
    page = doc[2]
    page.insert_text((72, 72), "4 Requirements", fontsize=14, fontname="hebo")
    cols, top, row_h = [72, 132, 432, 540], 90.0, 22.0
    for r, row in enumerate(REQUIREMENTS):
        y0 = top + r * row_h
        for c, cell in enumerate(row):
            page.insert_text((cols[c] + 4, y0 + 15), cell, fontsize=10, fontname="helv")
    bottom = top + len(REQUIREMENTS) * row_h
    for r in range(len(REQUIREMENTS) + 1):
        page.draw_line((cols[0], top + r * row_h), (cols[-1], top + r * row_h))
    for x in cols:
        page.draw_line((x, top), (x, bottom))
    level, heading, paras = EVALUATION
    page.insert_text((72, bottom + 40), heading, fontsize=14, fontname="hebo")
    page.insert_textbox(pymupdf.Rect(72, bottom + 52, 540, bottom + 200), paras[0], fontsize=10)
    doc.save(path)
    doc.close()
    return path


def make_docx(path: Path) -> Path:
    """DOCX with Title/Heading styles and a requirements table."""
    import docx

    document = docx.Document()
    for level, heading, paras in [*SECTIONS, (1, "4 Requirements", []), EVALUATION]:
        if level == 0:
            document.add_heading(heading, level=0)
        else:
            document.add_heading(heading, level=level)
        for para in paras:
            document.add_paragraph(para)
        if heading == "4 Requirements":
            table = document.add_table(rows=0, cols=3)
            for row in REQUIREMENTS:
                cells = table.add_row().cells
                for cell, value in zip(cells, row, strict=True):
                    cell.text = value
    document.save(str(path))
    return path


def make_xlsx(path: Path) -> Path:
    """Requirements matrix workbook."""
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Requirements"
    for row in REQUIREMENTS:
        sheet.append(row)
    workbook.save(path)
    return path


def make_pptx(path: Path) -> Path:
    """Two-slide deck: title + bullets with notes, and a table slide."""
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Our Understanding"
    slide.placeholders[1].text_frame.text = "Care managers need faster prior authorization"
    slide.notes_slide.notes_text_frame.text = "Synthetic speaker notes."
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Requirements Summary"
    shape = slide.shapes.add_table(len(REQUIREMENTS), 3, Inches(1), Inches(2), Inches(8), Inches(2))
    for r, row in enumerate(REQUIREMENTS):
        for c, value in enumerate(row):
            shape.table.cell(r, c).text = value
    prs.save(str(path))
    return path


def make_all(out_dir: Path) -> dict[str, Path]:
    """Write every fixture into ``out_dir`` and return them by format."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "pdf": make_pdf(out_dir / "acme_rfp.pdf"),
        "docx": make_docx(out_dir / "acme_rfp.docx"),
        "xlsx": make_xlsx(out_dir / "acme_requirements.xlsx"),
        "pptx": make_pptx(out_dir / "acme_deck.pptx"),
    }


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "acme-fixtures")
    for kind, file in make_all(target).items():
        print(f"{kind}: {file}")
