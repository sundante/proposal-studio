from pathlib import Path

import pytest

from studio.config import RagConfig
from studio.ingest import IngestError, chunk_sections, extract_sections, ingest
from studio.models import Section
from studio.rag import VectorIndex
from tests.fakes import FakeLLM

EMBED = "nomic-embed-text"


def by_label(sections: list[Section]) -> dict[str, Section]:
    return {s.section_label: s for s in sections}


def test_pdf_headings_pages_and_table(rfp_files: dict[str, Path]) -> None:
    sections = by_label(extract_sections(rfp_files["pdf"]))
    submission = sections["2 Submission Instructions"]
    assert submission.page == 1 and "March 15, 2027" in submission.text
    compliance = sections["3 Scope of Work > 3.2 Compliance"]
    assert compliance.page == 2 and "HITRUST" in compliance.text
    table = sections["4 Requirements"]
    assert table.kind == "table" and table.page == 3
    assert "ID: R-01; Requirement: Single sign-on with the Acme identity provider" in table.text


def test_docx_heading_styles_and_table(rfp_files: dict[str, Path]) -> None:
    sections = by_label(extract_sections(rfp_files["docx"]))
    assert "1 Introduction > 1.1 Background" in sections
    assert sections["2 Submission Instructions"].page is None
    table = sections["4 Requirements"]
    assert table.kind == "table"
    assert table.text.splitlines()[1].startswith("ID: R-02; Requirement: Model monitoring")


def test_xlsx_rows_with_headers(rfp_files: dict[str, Path]) -> None:
    [sheet] = extract_sections(rfp_files["xlsx"])
    assert sheet.heading_path == ["Requirements"]
    assert sheet.text.splitlines()[0].startswith("Row 2 — ID: R-01; Requirement:")


def test_pptx_slides_titles_notes_tables(rfp_files: dict[str, Path]) -> None:
    sections = extract_sections(rfp_files["pptx"])
    first = next(s for s in sections if s.page == 1)
    assert first.heading_path == ["Our Understanding"]
    assert "Our Understanding" not in first.text
    assert "Speaker notes: Synthetic speaker notes." in first.text
    assert any(s.page == 2 and s.kind == "table" and "R-03" in s.text for s in sections)


def test_markdown_and_text(tmp_path: Path) -> None:
    md = tmp_path / "notes.md"
    md.write_text("# Overview\nIntro text.\n\n## Timeline\nGo-live in Q3.\n")
    assert [s.section_label for s in extract_sections(md)] == ["Overview", "Overview > Timeline"]
    txt = tmp_path / "rfp.txt"
    txt.write_text("1 Scope\nBuild things.\n\n1.1 Details\nMore detail.\n")
    assert [s.section_label for s in extract_sections(txt)] == ["1 Scope", "1 Scope > 1.1 Details"]


def test_unsupported_file(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG")
    with pytest.raises(IngestError, match="unsupported"):
        extract_sections(path)


def test_chunks_respect_size_sections_and_overlap() -> None:
    para = "Sentence number {n} describes the Acme Health Plan data platform in detail."
    text = "\n\n".join(para.format(n=n) for n in range(200))
    sections = [
        Section(file="a.pdf", heading_path=["1 Scope"], page=1, text=text),
        Section(file="a.pdf", heading_path=["2 Terms"], page=2, text="Short section."),
    ]
    chunks = chunk_sections(sections, "hash", tokens=200, overlap=40)
    scope = [c for c in chunks if c.section == "1 Scope"]
    assert len(scope) > 3
    assert all(len(c.text) <= 200 * 4 for c in chunks)
    assert {c.section for c in chunks} == {"1 Scope", "2 Terms"}
    assert chunks[-1].text == "Short section." and chunks[-1].page == 2
    for prev, nxt in zip(scope, scope[1:], strict=False):
        assert prev.text[-60:].split()[-1] in nxt.text[:200]  # overlap carried forward
    assert len({c.id for c in chunks}) == len(chunks)


def test_long_paragraph_is_split() -> None:
    words = " ".join(f"word{n}" for n in range(2000))
    chunks = chunk_sections([Section(file="x.txt", text=words)], "h", tokens=100, overlap=10)
    assert len(chunks) > 5 and all(len(c.text) <= 400 for c in chunks)


def _opp(tmp_path: Path) -> Path:
    opp = tmp_path / "workspace" / "acme"
    (opp / "input").mkdir(parents=True)
    return opp


def test_ingest_copies_indexes_and_is_incremental(tmp_path: Path, rfp_files) -> None:
    opp, llm, cfg = _opp(tmp_path), FakeLLM(), RagConfig()
    report = ingest(opp, [rfp_files["pdf"], rfp_files["docx"]], llm, cfg, EMBED)
    assert sorted(report.new) == ["acme_rfp.docx", "acme_rfp.pdf"]
    assert (opp / "input" / "acme_rfp.pdf").exists()
    assert report.chunks_added == report.total_chunks > 0

    again = ingest(opp, [rfp_files["pdf"]], llm, cfg, EMBED)
    assert again.unchanged == ["acme_rfp.pdf"] and again.chunks_added == 0
    assert again.total_chunks == report.total_chunks


def test_ingest_input_folder_detects_changes_and_removals(tmp_path: Path, rfp_files) -> None:
    opp, llm, cfg = _opp(tmp_path), FakeLLM(), RagConfig()
    ingest(opp, [rfp_files["pdf"], rfp_files["xlsx"]], llm, cfg, EMBED)
    note = opp / "input" / "addendum.txt"
    note.write_text("1 Addendum\nThe deadline moves to April 1, 2027.\n")
    report = ingest(opp, [], llm, cfg, EMBED)
    assert report.new == ["addendum.txt"]
    note.write_text("1 Addendum\nThe deadline moves to April 8, 2027.\n")
    (opp / "input" / "acme_requirements.xlsx").unlink()
    report = ingest(opp, [], llm, cfg, EMBED)
    assert report.changed == ["addendum.txt"]
    assert report.removed == ["acme_requirements.xlsx"]
    index = VectorIndex(opp / "index")
    assert index.files() == ["acme_rfp.pdf", "addendum.txt"]
    assert not any("April 1," in h.chunk.text for h in index.search([1.0] * 256, 50))


def test_ingest_blocks_on_phi_until_confirmed(tmp_path: Path) -> None:
    opp, llm, cfg = _opp(tmp_path), FakeLLM(), RagConfig()
    src = tmp_path / "leaky.txt"
    src.write_text("1 Members\nMember SSN 123-45-6789 appears here.\n")
    report = ingest(opp, [src], llm, cfg, EMBED)
    assert report.blocked and report.phi_hits[0].kind == "ssn"
    assert not (opp / "input" / "leaky.txt").exists()
    assert not (opp / "index" / "manifest.json").exists()

    report = ingest(opp, [src], llm, cfg, EMBED, confirm_phi=True)
    assert not report.blocked and report.new == ["leaky.txt"]


def test_ingest_skips_unsupported(tmp_path: Path) -> None:
    opp = _opp(tmp_path)
    src = tmp_path / "logo.png"
    src.write_bytes(b"x")
    report = ingest(opp, [src], FakeLLM(), RagConfig(), EMBED)
    assert report.skipped == {"logo.png": "unsupported file type"}


def test_embed_model_change_rebuilds(tmp_path: Path, rfp_files) -> None:
    opp, llm, cfg = _opp(tmp_path), FakeLLM(), RagConfig()
    ingest(opp, [rfp_files["pdf"]], llm, cfg, EMBED)
    messages: list[str] = []
    report = ingest(opp, [rfp_files["pdf"]], llm, cfg, "other-embed", on_status=messages.append)
    assert report.changed == [] and report.new == ["acme_rfp.pdf"]
    assert any("rebuilding" in m for m in messages)
