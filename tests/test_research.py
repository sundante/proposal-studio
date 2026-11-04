from pathlib import Path

import pytest

from studio.config import load_config
from studio.ingest import IngestError, index_library, ingest
from studio.rag import library_index
from studio.research import Budget, ResearchError, run_research, save_report
from tests.conftest import REPO_ROOT
from tests.fakes import FakeLLM
from tests.fixtures.make_library import make_library
from tests.fixtures.make_reference import make_reference

EMBED = "nomic-embed-text"
QUESTION = "How should we approach FHIR R4 integration and HIPAA safeguards?"

PLAN = {
    "sub_questions": [
        {
            "question": "What FHIR R4 integration patterns exist?",
            "rephrasings": ["Bulk Data export", "SMART on FHIR"],
        },
        {
            "question": "Which HIPAA technical safeguards apply?",
            "rephrasings": ["encryption audit controls", "access control"],
        },
        {
            "question": "What does the zebra migration policy say?",
            "rephrasings": ["zebra", "quokka"],
        },
    ]
}
FINDING_FHIR = {
    "points": [
        {"text": "Nightly Bulk Data export feeds a data platform", "excerpts": [1]},
        {"text": "Invented point", "excerpts": [99]},
    ],
    "evidence": "strong",
    "missing": "",
}
FINDING_HIPAA = {
    "points": [{"text": "Technical safeguards include access and audit controls", "excerpts": [1]}],
    "evidence": "strong",
    "missing": "",
}
FINDING_NONE = {"points": [], "evidence": "none", "missing": "Nothing about zebras"}
SYNTH = {
    "summary": ["Use Bulk Data export plus HIPAA technical safeguards"],
    "implications": ["Address FHIR R4 and encryption explicitly in the proposal"],
    "gaps": ["Zebra migration policy"],
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    make_reference(tmp_path / "library" / "reference")
    make_library(tmp_path / "library" / "proposals")
    cfg = load_config(REPO_ROOT)
    for name in ("reference", "proposals"):
        index_library(tmp_path, name, FakeLLM(), cfg.rag, EMBED)
    return tmp_path


def llm(findings=None, gap=None) -> FakeLLM:
    return FakeLLM(
        {
            "ResearchPlan": PLAN,
            "FindingDraft": findings or [FINDING_FHIR, FINDING_HIPAA, FINDING_NONE, FINDING_NONE],
            "GapPlan": gap or {"items": [{"sub_question": 3, "queries": ["animal policy"]}]},
            "Synthesis": SYNTH,
        }
    )


def test_index_library_in_place_with_subfolders(tmp_path: Path) -> None:
    make_reference(tmp_path / "library" / "reference")
    cfg = load_config(REPO_ROOT)
    report = index_library(tmp_path, "reference", FakeLLM(), cfg.rag, EMBED)
    assert sorted(report.new) == ["hipaa_overview.md", "standards/fhir_r4_notes.pdf"]
    assert not (tmp_path / "library" / "reference" / "input").exists()  # indexed in place
    again = index_library(tmp_path, "reference", FakeLLM(), cfg.rag, EMBED)
    assert again.unchanged and not again.new
    (tmp_path / "library" / "reference" / "hipaa_overview.md").unlink()
    gone = index_library(tmp_path, "reference", FakeLLM(), cfg.rag, EMBED)
    assert gone.removed == ["hipaa_overview.md"]
    assert library_index(tmp_path, "reference").files() == ["standards/fhir_r4_notes.pdf"]
    with pytest.raises(IngestError, match="Unknown library collection"):
        index_library(tmp_path, "secrets", FakeLLM(), cfg.rag, EMBED)


def test_library_phi_blocks(tmp_path: Path) -> None:
    folder = tmp_path / "library" / "reference"
    folder.mkdir(parents=True)
    (folder / "leak.txt").write_text("Patient SSN 123-45-6789\n")
    report = index_library(tmp_path, "reference", FakeLLM(), load_config(REPO_ROOT).rag, EMBED)
    assert report.blocked and len(library_index(tmp_path, "reference")) == 0


def test_research_end_to_end(root: Path) -> None:
    fake = llm()
    statuses: list[str] = []
    report = run_research(QUESTION, root, fake, load_config(REPO_ROOT), on_status=statuses.append)
    assert report.sources_searched == ["proposals", "reference"]  # no opp: RFP skipped
    fhir, hipaa, zebra = report.findings
    assert fhir.points[0][0] == "Nightly Bulk Data export feeds a data platform"
    assert fhir.points[0][1][0].startswith("[") and len(fhir.points) == 1  # bad ref dropped
    assert any("Dropped 1 uncited point" in n for n in report.notes)
    assert zebra.gap_round and not zebra.points  # gap round ran, still nothing
    assert report.llm_calls == 1 + 3 + 1 + len([f for f in report.findings if f.gap_round]) + 1
    assert report.llm_calls <= 12
    assert "Gap check for" in " ".join(statuses)
    md = report.to_markdown()
    for heading in ("# Research:", "## Summary", "## Findings", "## Implications for this RFP"):
        assert heading in md
    assert "## Gaps (not covered in the library)" in md and "- Zebra migration policy" in md
    assert "## Sources" in md and "_Evidence: strong_" in md


def test_pdf_and_pptx_citation_formats(root: Path) -> None:
    from studio.research import Excerpt, open_sources, retrieve_multi

    sources = open_sources(root, load_config(REPO_ROOT), None)
    hits = retrieve_multi(["Bulk Data export", "MLOps pipelines"], sources, FakeLLM(), 4, 20)
    cites = {e.cite for e in hits}
    assert any(c.startswith("[fhir_r4_notes.pdf, p.") for c in cites)
    assert any(c.startswith("[example_hospital_deck.pptx, slide ") for c in cites)
    assert all(isinstance(e, Excerpt) for e in hits)


def test_call_cap_skips_gap_round_but_keeps_synthesis(root: Path) -> None:
    fake = llm()
    report = run_research(QUESTION, root, fake, load_config(REPO_ROOT), max_calls=5)
    assert report.llm_calls == 5  # plan + 3 findings + synthesis
    assert "Gap check skipped" in " ".join(report.notes)
    assert report.summary == SYNTH["summary"]
    tiny = run_research(QUESTION, root, llm(), load_config(REPO_ROOT), max_calls=3)
    assert tiny.llm_calls == 3 and len(tiny.findings) == 1  # plan sized to the budget


def test_includes_rfp_when_opportunity_given(root: Path, rfp_files) -> None:
    opp = root / "workspace" / "acme"
    ingest(opp, [rfp_files["pdf"]], FakeLLM(), load_config(REPO_ROOT).rag, EMBED)
    report = run_research(QUESTION, root, llm(), load_config(REPO_ROOT), opp_dir=opp)
    assert report.sources_searched == ["rfp", "proposals", "reference"]


def test_nothing_indexed_and_empty_question(tmp_path: Path) -> None:
    with pytest.raises(ResearchError, match="library index"):
        run_research(QUESTION, tmp_path, FakeLLM(), load_config(REPO_ROOT))
    with pytest.raises(ResearchError, match="Ask a question"):
        run_research("  ", tmp_path, FakeLLM(), load_config(REPO_ROOT))


def test_save_report_never_overwrites(root: Path, tmp_path: Path) -> None:
    report = run_research(QUESTION, root, llm(), load_config(REPO_ROOT), max_calls=5)
    first = save_report(report, tmp_path / "out")
    second = save_report(report, tmp_path / "out")
    assert first != second and second.name.endswith("-2.md")
    assert first.read_text().startswith("# Research: How should we approach")


def test_budget() -> None:
    budget = Budget(3)
    assert budget.can(2, reserve=1) and not budget.can(3, reserve=1)
    for _ in range(3):
        budget.spend()
    with pytest.raises(ResearchError):
        budget.spend()
