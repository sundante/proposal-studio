"""Generate a synthetic past-proposal library for "Example Hospital" (PPTX + DOCX).

All content is fictional. Usage: ``python -m tests.fixtures.make_library OUTDIR``.
"""

from __future__ import annotations

import sys
from pathlib import Path

CLIENT = "Example Hospital"

SLIDES: list[tuple[str, list[str]]] = [
    (f"Proposal for {CLIENT}", ["Prepared for the Example Hospital board", "June 2024"]),
    (
        "Our understanding",
        [
            f"{CLIENT} clinicians spend hours on manual chart review",
            "Data is split across the EHR, claims and lab systems",
            "Leadership wants AI with clear governance",
        ],
    ),
    (
        "A complete AI platform",
        [
            "Development workbench for notebooks, prompts and evaluation",
            "MLOps and LLMOps pipelines with versioned models and prompts",
            "Observability for quality, drift and cost",
            "Model registry with approvals and audit trail",
        ],
    ),
    (
        "Responsible AI and compliance",
        [
            "HIPAA safeguards: encryption, access control, audit logging",
            "Controls mapped to the HITRUST CSF",
            "Bias and safety review before every release",
        ],
    ),
    (
        "Why us",
        [
            f"Reduced readmissions 18% at {CLIENT} in 2023",
            "Saved $1.2M in the first year",
            "Healthcare-first team led by Jane Smith (jane.smith@example.org)",
        ],
    ),
    ("Pricing", ["Phase 1: $450,000 fixed fee", "Phase 2: time and materials"]),
]

DOC_SECTIONS: list[tuple[str, list[str]]] = [
    (
        "AI maturity model",
        [
            "Foundation: data platform, governance and a first production use case.",
            "Scale: three to five use cases on shared components and MLOps.",
            "Optimize: continuous evaluation and self-service AI for business teams.",
        ],
    ),
    (
        "Next steps",
        [
            "Weeks 1-2: discovery workshops and data access.",
            "Weeks 3-8: first use case built with clinicians.",
            f"Weeks 9-12: pilot at {CLIENT} and go/no-go review on March 3, 2025.",
        ],
    ),
]


def make_pptx(path: Path) -> Path:
    """Past proposal deck: one slide per entry in SLIDES."""
    from pptx import Presentation

    prs = Presentation()
    for title, bullets in SLIDES:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        frame = slide.placeholders[1].text_frame
        frame.text = bullets[0]
        for bullet in bullets[1:]:
            frame.add_paragraph().text = bullet
    prs.save(str(path))
    return path


def make_docx(path: Path) -> Path:
    """Past proposal document with Heading 1 sections."""
    import docx

    document = docx.Document()
    document.add_heading(f"{CLIENT} AI Program Proposal", level=0)
    for heading, paras in DOC_SECTIONS:
        document.add_heading(heading, level=1)
        for para in paras:
            document.add_paragraph(para)
    document.save(str(path))
    return path


def make_library(out_dir: Path) -> dict[str, Path]:
    """Write both files into ``out_dir`` (e.g. ``library/proposals``)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "pptx": make_pptx(out_dir / "example_hospital_deck.pptx"),
        "docx": make_docx(out_dir / "example_hospital_proposal.docx"),
    }


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "library/proposals")
    for kind, file in make_library(target).items():
        print(f"{kind}: {file}")
