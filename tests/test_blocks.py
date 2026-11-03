from pathlib import Path

import pytest
import yaml

from studio.blocks import (
    Block,
    BlockError,
    anonymise,
    compute_content_hash,
    harvest,
    is_protected,
    load_blocks,
    save_block,
    search_blocks,
)
from studio.config import DeckConfig
from tests.fakes import FakeLLM
from tests.fixtures.make_library import make_library

EMBED = "nomic-embed-text"


def result(slide_type: str, title: str, points: list[str], **kw) -> dict:
    return {
        "reusable": True,
        "slide_type": slide_type,
        "title": title,
        "body_points": points,
        "tags": kw.get("tags", []),
        "capability": kw.get("capability", ""),
        "client_names": kw.get("client_names", []),
        "uncertain": kw.get("uncertain", []),
    }


# One canned answer per harvest unit, in order (see tests/fixtures/make_library.py).
CANNED = [
    result(
        "understanding",
        "Clinical teams lose time to manual review",
        ["Example Hospital clinicians spend hours on chart review", "Data split across systems"],
        client_names=["Example Hospital"],
        tags=["EHR", "Chart Review"],
    ),
    result(
        "platform",
        "A complete AI platform",
        ["Development workbench", "MLOps and LLMOps pipelines", "Observability for drift"],
        tags=["mlops", "llmops", "observability"],
    ),
    result(
        "governance",
        "Responsible AI and compliance",
        ["HIPAA safeguards", "Controls mapped to the HITRUST CSF"],
        tags=["hipaa", "hitrust"],
    ),
    result(
        "why_us",
        "Proven healthcare results",
        ["Reduced readmissions 18% in 2023", "Saved $1.2M in year one", "Email jane@example.org"],
        uncertain=["Is the 18% figure public?"],
        tags=["outcomes"],
    ),
    result("maturity", "AI maturity model", ["Foundation", "Scale", "Optimize"], tags=["roadmap"]),
    {**result("next_steps", "Pilot plan", ["Pilot"]), "reusable": False},
]


@pytest.fixture
def library(tmp_path: Path) -> Path:
    make_library(tmp_path / "library" / "proposals")
    return tmp_path


def test_anonymise() -> None:
    text = (
        "Example Hospital's team met on June 3, 2024 and 2023 Q4; budget $1.2M (call 555-123-4567)"
    )
    out = anonymise(text, ["Example Hospital"])
    assert out == "{{client}} team met on {{date}} and {{date}} Q4; budget {{amount}} (call )"
    assert anonymise("ISO 27001 and SOC 2", []) == "ISO 27001 and SOC 2"


def test_harvest_writes_anonymised_blocks(library: Path) -> None:
    llm = FakeLLM({"HarvestResult": CANNED})
    report = harvest(library, llm, DeckConfig(), clients=["Example Hospital"])
    assert len(report.new) == 5 and report.skipped == 1 and not report.failed
    blocks = {b.slide_type: b for b in load_blocks(library)}
    understanding = blocks["understanding"]
    assert understanding.body_points[0] == "{{client}} clinicians spend hours on chart review"
    assert understanding.tags == ["chart review", "ehr"]
    assert understanding.source_file == "example_hospital_deck.pptx"
    assert understanding.source_ref == "slide 2"
    why = blocks["why_us"]
    assert why.body_points[:2] == [
        "Reduced readmissions 18% in {{date}}",
        "Saved {{amount}} in year one",
    ]
    assert "jane@" not in " ".join(why.body_points)
    assert why.needs_review and any("18%" in n for n in why.review_notes)
    assert report.flagged == [why.id]
    text = (library / "library" / "blocks" / "why_us" / f"{why.id}.yaml").read_text()
    assert text.startswith("# Proposal Studio block.") and "Example Hospital" not in text


def test_reharvest_is_incremental_and_respects_edits(library: Path) -> None:
    harvest(library, FakeLLM({"HarvestResult": CANNED}), DeckConfig())
    llm = FakeLLM({"HarvestResult": CANNED})
    again = harvest(library, llm, DeckConfig())
    assert again.unchanged == 6 and not llm.calls  # nothing changed: no LLM calls

    blocks = {b.slide_type: b for b in load_blocks(library)}
    platform = blocks["platform"]
    platform.title = "Our curated platform story"  # hand edit, no flag
    save_block(library, platform)
    governance = blocks["governance"].model_copy(update={"edited": True})
    save_block(library, governance)
    assert is_protected(platform) and is_protected(governance)

    (library / "library" / ".index" / "harvest.json").unlink()  # force a full re-harvest
    report = harvest(library, FakeLLM({"HarvestResult": CANNED}), DeckConfig())
    assert sorted(report.protected) == sorted([platform.id, governance.id])
    assert len(report.refreshed) == 3 and not report.new  # same ids, no duplicates
    kept = {b.slide_type: b for b in load_blocks(library)}
    assert kept["platform"].title == "Our curated platform story"
    assert len(load_blocks(library)) == 5


def test_missing_library(tmp_path: Path) -> None:
    with pytest.raises(BlockError, match="No past proposals"):
        harvest(tmp_path, FakeLLM(), DeckConfig())


def test_invalid_block_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "library" / "blocks" / "platform" / "x.yaml"
    bad.parent.mkdir(parents=True)
    bad.write_text(yaml.safe_dump({"id": "x", "unknown": 1}))
    with pytest.raises(BlockError, match="not a valid block"):
        load_blocks(tmp_path)


def _block(id_: str, slide_type: str, title: str, points: list[str], **kw) -> Block:
    block = Block(id=id_, slide_type=slide_type, title=title, body_points=points, **kw)
    return block.model_copy(update={"content_hash": compute_content_hash(block)})


def test_search_ranks_and_filters(tmp_path: Path) -> None:
    for block in (
        _block(
            "mlops-1",
            "platform",
            "MLOps pipelines",
            ["Versioned models and pipelines"],
            tags=["mlops"],
        ),
        _block(
            "obs-1",
            "platform",
            "Observability",
            ["Drift and cost dashboards"],
            tags=["observability"],
        ),
        _block("hipaa-1", "governance", "HIPAA safeguards", ["Encryption and audit logging"]),
        _block("draft-1", "platform", "Draft pipelines", ["pipelines"], needs_review=True),
    ):
        save_block(tmp_path, block)
    llm = FakeLLM()
    hits = search_blocks(tmp_path, "drift dashboards", llm, EMBED, slide_type="platform")
    assert hits[0][0].id == "obs-1"
    assert {b.slide_type for b, _ in hits} == {"platform"}
    clean = search_blocks(tmp_path, "pipelines", llm, EMBED, include_flagged=False)
    assert "draft-1" not in {b.id for b, _ in clean}
    # editing a block re-embeds it
    edited = _block("hipaa-1", "governance", "Dashboards for compliance drift", ["drift"])
    save_block(tmp_path, edited)
    top = search_blocks(tmp_path, "compliance drift", llm, EMBED, k=1)[0][0]
    assert top.id == "hipaa-1" and top.title == "Dashboards for compliance drift"


def test_uncertain_notes_are_anonymised_and_deduplicated(library: Path) -> None:
    noisy = [
        result(
            "understanding",
            "Clinical teams lose time",
            ["Clinicians spend hours on chart review", "Review set for March 3"],
            client_names=["Example Hospital"],
            uncertain=[
                "Example Hospital",
                "Clinicians spend hours on chart review",
                "Example Hospital's board deck",
            ],
        ),
        *CANNED[1:],
    ]
    harvest(library, FakeLLM({"HarvestResult": noisy}), DeckConfig())
    block = next(b for b in load_blocks(library) if b.slide_type == "understanding")
    assert block.body_points[1] == "Review set for {{date}}"
    assert block.review_notes == ["model unsure: {{client}} board deck"]
    text = (library / "library" / "blocks" / "understanding" / f"{block.id}.yaml").read_text()
    assert "Example Hospital" not in text
