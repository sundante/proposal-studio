import json
from pathlib import Path

import openpyxl
import pytest

from studio.config import RagConfig
from studio.digest import (
    MATRIX_COLUMNS,
    Digest,
    DigestError,
    build_digest,
    export_matrix,
    group_chunks,
    is_stale,
    load_digest,
    render_summary,
)
from studio.ingest import ingest
from studio.models import Chunk, Cite
from tests.fakes import FakeLLM


def chunk(i: int, text: str, file: str = "rfp.pdf", section: str = "S", page: int | None = 1):
    return Chunk(id=f"c{i}", file=file, file_hash="h", section=section, page=page, text=text)


def test_grouping_keeps_order_size_and_file_boundaries() -> None:
    chunks = [chunk(i, "x" * 1000) for i in range(5)] + [chunk(9, "y" * 100, file="b.docx")]
    groups = group_chunks(chunks, max_tokens=500)  # 2000 chars per group
    assert [[c.id for c in g] for g in groups] == [["c0", "c1"], ["c2", "c3"], ["c4"], ["c9"]]
    big = group_chunks([chunk(0, "z" * 9000), chunk(1, "small")], max_tokens=500)
    assert [len(g) for g in big] == [1, 1]


# --- build_digest with canned map outputs ---------------------------------------------------

REQ_TABLE = (
    "ID: R-01; Requirement: Single sign-on with the Acme identity provider; Mandatory: Yes\n"
    "ID: R-02; Requirement: Model monitoring and drift alerts; Mandatory: No"
)


@pytest.fixture
def opp(tmp_path: Path) -> Path:
    """An opportunity whose index holds two files -> two section groups."""
    opp = tmp_path / "workspace" / "acme"
    inp = tmp_path / "src"
    inp.mkdir()
    (inp / "a.txt").write_text(
        "1 Submission\nProposals are due March 15, 2027 on the Acme portal. Limit 30 slides.\n\n"
        "2 Background\nCare managers review claims manually in a legacy portal.\n"
    )
    (inp / "b.md").write_text(f"# Requirements\n\n{REQ_TABLE}\n\n# Compliance\nHIPAA applies.\n")
    ingest(opp, [inp / "a.txt", inp / "b.md"], FakeLLM(), RagConfig(), "nomic-embed-text")
    return opp


GROUP_A = {
    "opportunity": {
        "client": "Acme Health Plan",
        "title": "Enterprise AI Platform",
        "due_date": "March 15, 2027",
        "page_or_slide_limits": "30 slides",
        "excerpts": [1],
    },
    "business_problems": [
        {"statement": "Care managers review claims manually", "excerpts": [2]},
        {"statement": "Invented problem with a bad reference", "excerpts": [42]},
    ],
    "current_state": [{"item": "Manual review in a legacy portal", "excerpts": [2]}],
    "requirements": [
        {
            "rfp_id": "R-01",
            "text": "Single sign-on with the Acme identity provider",
            "type": "functional",
            "mandatory": False,
            "excerpts": [2],
        }
    ],
    "systems_mentioned": [{"name": "Legacy portal", "role": "care management today"}],
    "open_questions": ["Is SSO via SAML or OIDC?"],
}
GROUP_B = {
    "opportunity": {"due_date": "April 1, 2027", "excerpts": [1]},
    "business_problems": [{"statement": "Care managers review claims manually.", "excerpts": [1]}],
    "requirements": [
        {  # model copies R-01 onto the wrong row: must be corrected from the table text
            "rfp_id": "R-01",
            "text": "Model monitoring and drift alerts",
            "type": "nonfunctional",
            "mandatory": False,
            "excerpts": [1],
        },
        {  # near-duplicate of group A's requirement: merges, mandatory OR'd, cites unioned
            "rfp_id": None,
            "text": "Single sign-on with Acme identity provider",
            "type": "functional",
            "mandatory": True,
            "excerpts": [1],
        },
        {"text": "Support FHIR R4", "type": "functional", "mandatory": True, "excerpts": [2]},
    ],
    "compliance": [
        {"framework": "HIPAA", "detail": "HIPAA applies", "excerpts": [2]},
        {"framework": "HIPAA", "detail": "HIPAA applies.", "excerpts": [2]},
    ],
    "risks_and_red_flags": [{"item": "No pricing template", "excerpts": [9]}],
    "open_questions": ["Is SSO via SAML or OIDC?", "What is the go-live date?"],
}


def test_build_digest_merges_cites_and_flags(opp: Path) -> None:
    llm = FakeLLM({"DigestPart": [GROUP_A, GROUP_B]})
    statuses: list[str] = []
    report = build_digest(opp, llm, RagConfig(), on_status=statuses.append)
    d = report.digest
    assert report.groups == 2 and "Reading section group 2/2…" in statuses

    assert d.opportunity.client == "Acme Health Plan"
    assert d.opportunity.due_date == "March 15, 2027"  # first value wins…
    conflict = d.risks_and_red_flags[0]  # …and the conflict is flagged, never silent
    assert "Conflicting due date" in conflict.item and "April 1, 2027" in conflict.item

    assert [p.statement for p in d.business_problems] == ["Care managers review claims manually"]
    assert len(d.business_problems[0].evidence) == 2  # cites from both groups

    by_text = {r.text: r for r in d.requirements}
    sso = by_text["Single sign-on with the Acme identity provider"]
    assert sso.id == "R-01" and sso.mandatory is True and len(sso.cite) == 2
    # The copied "R-01" can't be disproved here (both rows share one line), so it is dropped.
    assert by_text["Model monitoring and drift alerts"].id == "REQ-001"
    assert by_text["Support FHIR R4"].id == "REQ-002"
    assert len({r.id for r in d.requirements}) == len(d.requirements) == 3

    assert len(d.compliance) == 1
    assert d.open_questions == ["Is SSO via SAML or OIDC?", "What is the go-live date?"]
    assert any("Dropped 2 items" in w for w in report.warnings)  # bad refs 42 and 9
    assert any("invalid excerpt references" in w for w in report.warnings)

    saved = load_digest(opp)
    assert saved == Digest.model_validate_json((opp / "digest.json").read_text())
    meta = json.loads((opp / "digest.meta.json").read_text())
    assert set(meta["sources"]) == {"a.txt", "b.md"}
    assert is_stale(opp) is False


def test_requirement_id_checked_against_table_rows() -> None:
    from studio.digest import _requirement_id

    group = [chunk(0, "intro"), chunk(1, REQ_TABLE)]
    assert _requirement_id("R-01", "Model monitoring and drift alerts", [2], group) == "R-02"
    assert (
        _requirement_id(None, "Single sign-on with the Acme identity provider", [2], group)
        == "R-01"
    )
    assert _requirement_id("R-09", "Something unrelated entirely", [2], group) == ""
    assert (
        _requirement_id("3.2.1", "Encrypt data", [1], [chunk(0, "3.2.1 Encrypt data at rest")])
        == "3.2.1"
    )


def test_failed_group_is_skipped(opp: Path) -> None:
    llm = FakeLLM({"DigestPart": ["not json", "not json", "not json", GROUP_B]})
    report = build_digest(opp, llm, RagConfig())
    assert report.failed_groups == 1 and "Skipped section group 1" in report.warnings[0]
    assert report.digest.requirements


def test_all_groups_failing_raises(opp: Path) -> None:
    with pytest.raises(DigestError, match="invalid output"):
        build_digest(opp, FakeLLM({"DigestPart": "nope"}), RagConfig())


def test_nothing_ingested(tmp_path: Path) -> None:
    with pytest.raises(DigestError, match="/ingest"):
        build_digest(tmp_path, FakeLLM(), RagConfig())


def test_stale_after_reingest(opp: Path, tmp_path: Path) -> None:
    build_digest(opp, FakeLLM({"DigestPart": [GROUP_A, GROUP_B]}), RagConfig())
    extra = tmp_path / "addendum.txt"
    extra.write_text("1 Addendum\nNew deadline.\n")
    ingest(opp, [extra], FakeLLM(), RagConfig(), "nomic-embed-text")
    assert is_stale(opp) is True


def sample_digest() -> Digest:
    cite = Cite(section="2 Submission", page=1)
    return Digest.model_validate(
        {
            "opportunity": {
                "title": "AI Platform",
                "client": "Acme Health Plan",
                "due_date": "Mar 15",
            },
            "business_problems": [{"statement": "Slow prior auth", "evidence": [cite]}],
            "current_state": [{"item": "Manual review", "evidence": [cite]}],
            "desired_outcomes": [{"item": "Automated triage", "evidence": [cite]}],
            "requirements": [
                {
                    "id": "R-01",
                    "text": "SSO",
                    "type": "functional",
                    "mandatory": True,
                    "cite": [cite],
                },
                {
                    "id": "R-02",
                    "text": "BI",
                    "type": "functional",
                    "mandatory": False,
                    "cite": [cite],
                },
            ],
            "evaluation_criteria": [{"criterion": "Technical", "weight": "40%", "cite": [cite]}],
            "compliance": [{"framework": "HIPAA", "detail": "Align", "cite": [cite]}],
            "systems_mentioned": [{"name": "Example EHR", "role": "clinical data"}],
            "risks_and_red_flags": [{"item": "Tight deadline", "cite": [cite]}],
            "open_questions": ["SSO protocol?"],
        }
    )


def test_render_summary() -> None:
    text = render_summary(sample_digest(), ["Skipped section group 3"])
    for heading in (
        "## RFP digest — AI Platform",
        "### Business problems",
        "### Today (before)",
        "### Wanted (after)",
        "### Requirements — 1 mandatory of 2 (2 functional)",
        "### Evaluation criteria",
        "### Compliance",
        "### Systems mentioned",
        "### Risks and red flags",
        "### Questions to ask the client",
        "### Warnings",
    ):
        assert heading in text
    assert "- **R-01** SSO [2 Submission, p.1]" in text and "…plus 1 optional" in text
    assert text.rstrip().splitlines()[-1].startswith("Next: `/outline`")


def test_export_matrix_versions(tmp_path: Path) -> None:
    first = export_matrix(sample_digest(), tmp_path, "acme")
    second = export_matrix(sample_digest(), tmp_path, "acme")
    assert first.name == "acme-requirements-v1.xlsx" and second.name == "acme-requirements-v2.xlsx"
    sheet = openpyxl.load_workbook(first).active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == MATRIX_COLUMNS
    assert rows[1][:5] == ("R-01", "SSO", "functional", "Yes", "[2 Submission, p.1]")
    assert sheet.freeze_panes == "A2"
