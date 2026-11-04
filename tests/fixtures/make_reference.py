"""Generate synthetic reference documents (HIPAA overview, FHIR R4 notes) for /research.

Content is generic and fictional-sounding summaries written for tests, not copied text.
Usage: ``python -m tests.fixtures.make_reference OUTDIR``.
"""

from __future__ import annotations

import sys
from pathlib import Path

HIPAA_MD = """# HIPAA overview (synthetic notes)

## Safeguards
Covered entities protect health information with administrative, physical and technical
safeguards. Technical safeguards include access control, audit controls, integrity controls
and transmission security such as encryption in transit.

## Business associates
Vendors that handle protected health information sign a business associate agreement and
must apply the same safeguards.

## Breach notification
Breaches of unsecured protected health information must be reported to affected individuals.
"""

FHIR_SECTIONS = [
    (
        "1 FHIR R4 basics",
        "FHIR R4 exposes clinical data as resources such as Patient, Encounter, Observation and "
        "Claim over a REST API. Bulk Data export supports population-level extracts in NDJSON.",
    ),
    (
        "2 Integration patterns",
        "Common patterns are nightly Bulk Data export into a data platform, event-driven "
        "subscriptions for near real time updates, and SMART on FHIR apps inside the EHR.",
    ),
    (
        "3 Prior authorization",
        "Payer prior authorization APIs build on FHIR resources so requests and decisions can be "
        "exchanged electronically, reducing manual faxes and phone calls.",
    ),
]


def make_fhir_pdf(path: Path) -> Path:
    """Two-page PDF with numbered headings."""
    import pymupdf

    doc = pymupdf.open()
    for n, (heading, text) in enumerate(FHIR_SECTIONS):
        if n in (0, 2):
            page = doc.new_page(width=612, height=792)
            y = 72.0
        page.insert_text((72, y), heading, fontsize=14, fontname="hebo")
        page.insert_textbox(pymupdf.Rect(72, y + 14, 540, y + 200), text, fontsize=10)
        y += 160
    doc.save(path)
    doc.close()
    return path


def make_reference(out_dir: Path) -> dict[str, Path]:
    """Write the reference documents into ``out_dir`` (e.g. ``library/reference``)."""
    (out_dir / "standards").mkdir(parents=True, exist_ok=True)
    hipaa = out_dir / "hipaa_overview.md"
    hipaa.write_text(HIPAA_MD, encoding="utf-8")
    return {"md": hipaa, "pdf": make_fhir_pdf(out_dir / "standards" / "fhir_r4_notes.pdf")}


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "library/reference")
    for kind, file in make_reference(target).items():
        print(f"{kind}: {file}")
