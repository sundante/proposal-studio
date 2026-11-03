from pathlib import Path

import pytest

from studio.blocks import save_block
from studio.config import StorylineConfig, load_config
from studio.deck.writer import (
    DeckError,
    edit_slide,
    facts_for,
    invention_flags,
    load_deck,
    write_deck,
)
from studio.render.renderer import render
from tests.conftest import REPO_ROOT
from tests.fakes import FakeLLM
from tests.test_blocks import _block
from tests.test_digest import sample_digest

SPINE = ["title", "understanding", "solution_architecture", "platform", "why_us"]


def platform(bullets: list[str], **kw) -> dict:
    return {
        "title": kw.get("title", "A complete AI platform for {{client}}"),
        "speaker_notes": "Walk through the platform.",
        "bullets": bullets,
        "used_blocks": kw.get("used_blocks", [1]),
        "used_facts": kw.get("used_facts", [1]),
    }


UNDERSTANDING = {
    "title": "Our understanding",
    "bullets": ["Slow prior auth", "Manual review", "Compliance pressure"],
    "used_facts": [1],
}
OK_PLATFORM = platform(
    ["MLOps pipelines with versioned models", "Drift dashboards", "Model registry"]
)


@pytest.fixture
def setup(tmp_path: Path):
    cfg = load_config(REPO_ROOT)
    slides = [s for s in cfg.storyline.slides if s.id in SPINE]
    cfg = cfg.model_copy(update={"storyline": StorylineConfig(slides=slides)})
    opp = tmp_path / "workspace" / "acme"
    opp.mkdir(parents=True)
    (opp / "digest.json").write_text(sample_digest().model_dump_json())
    for block in (
        _block(
            "mlops-1",
            "platform",
            "MLOps pipelines",
            ["Versioned models and pipelines"],
            tags=["mlops"],
        ),
        _block("obs-1", "platform", "Observability", ["Drift and cost dashboards"]),
    ):
        save_block(tmp_path, block)
    return tmp_path, opp, cfg


def llm_for(platform_outputs) -> FakeLLM:
    return FakeLLM(
        {"WriteUnderstandingContent": UNDERSTANDING, "WritePlatformContent": platform_outputs}
    )


def test_write_deck_end_to_end(setup) -> None:
    root, opp, cfg = setup
    statuses: list[str] = []
    report = write_deck(opp, "acme", root, llm_for(OK_PLATFORM), cfg, on_status=statuses.append)
    assert [s.id for s in report.deck.slides] == SPINE
    assert (opp / "outline.json").exists()  # built automatically
    assert "Writing slide 2/5: understanding…" in statuses

    title, understanding, arch, plat, why = report.deck.slides
    assert title.title == "AI Platform"
    assert title.subtitle == "Proposal for Acme Health Plan · Mar 15"
    assert plat.title == "A complete AI platform for Acme Health Plan"  # {{client}} filled
    assert plat.sources[0].startswith("block:") and "[2 Submission, p.1]" in plat.sources
    assert plat.review == []
    assert "written from the RFP facts only" in " ".join(understanding.review)
    assert why.bullets == ["Add content — no vetted blocks for why_us; run /harvest"]
    assert arch.layers[0].name == "Add layers" and why.review and arch.review

    qa = render(report.deck, cfg.layout_map, REPO_ROOT / cfg.layout_map.template, root, "acme").qa
    assert qa.ok, qa.to_markdown()
    assert any("review —" in w for w in qa.warnings)
    assert set(qa.missing_provenance) == {"why_us", "solution_architecture"}


def test_shorten_retry_then_ok(setup) -> None:
    root, opp, cfg = setup
    too_long = platform(["x " * 80, "Drift dashboards", "Model registry"])
    llm = llm_for([too_long, OK_PLATFORM])
    report = write_deck(opp, "acme", root, llm, cfg, slide_id=None)
    calls = [c for c in llm.calls if c["schema"] == "WritePlatformContent"]
    assert len(calls) == 2 and "Too long: bullets.0" in calls[1]["messages"][-1]["content"]
    assert report.deck.slides[3].review == []


def test_truncate_and_flag_when_still_too_long(setup) -> None:
    root, opp, cfg = setup
    too_long = platform(["word " * 40, "b", "c", "d", "e", "f"])
    report = write_deck(opp, "acme", root, llm_for(too_long), cfg)
    plat = report.deck.slides[3]
    assert len(plat.bullets) == 5 and plat.bullets[0].endswith("…")
    flags = " ".join(plat.review)
    assert "bullets[1] shortened to fit 110 chars" in flags and "kept 5 of 6" in flags


def test_invention_and_bad_reference_flags(setup) -> None:
    root, opp, cfg = setup
    invented = platform(
        ["Cut costs 40% with FedRAMP hosting", "Drift dashboards", "Model registry"],
        used_blocks=[1, 7],
    )
    plat = write_deck(opp, "acme", root, llm_for(invented), cfg).deck.slides[3]
    flags = " ".join(plat.review)
    assert "figure(s) not found in the blocks or RFP: 40%" in flags
    assert "certification(s) not in the blocks or RFP: FedRAMP" in flags
    assert "ignored unknown block/fact references: [7]" in flags
    assert plat.sources[0] == "block:mlops-1" or plat.sources[0] == "block:obs-1"


def test_invention_flags_allow_source_text() -> None:
    assert invention_flags("HIPAA and 30 slides", "HIPAA applies; limit 30 slides") == []


def test_single_slide_regenerate_and_edit(setup) -> None:
    root, opp, cfg = setup
    write_deck(opp, "acme", root, llm_for(OK_PLATFORM), cfg)
    first = load_deck(opp)
    new = platform(["Pipelines", "Dashboards", "Registry"], title="Platform v2")
    report = write_deck(opp, "acme", root, llm_for(new), cfg, slide_id="platform")
    assert report.written == ["platform"]
    second = load_deck(opp)
    assert second.slides[3].title == "Platform v2"
    assert second.slides[1] == first.slides[1]  # untouched
    assert len(list((opp / "history").glob("deck-*.json"))) == 1

    edited = platform(["Pipelines", "Dashboards", "FHIR-ready registry"], title="Platform v2")
    report = edit_slide(opp, root, llm_for(edited), cfg, "platform", "mention FHIR")
    assert "-- Registry" in report.diff and "+- FHIR-ready registry" in report.diff
    assert load_deck(opp).slides[3].bullets[2] == "FHIR-ready registry"
    with pytest.raises(DeckError, match="title slide"):
        edit_slide(opp, root, llm_for(edited), cfg, "title", "x")
    with pytest.raises(DeckError, match="isn't an included slide"):
        write_deck(opp, "acme", root, llm_for(OK_PLATFORM), cfg, slide_id="governance")


def test_facts_for_puts_mandatory_first() -> None:
    facts = facts_for("platform", sample_digest())
    assert facts[0].text.startswith("R-01 (mandatory)") and facts[0].cite == "[2 Submission, p.1]"


def test_requires_digest(tmp_path: Path) -> None:
    with pytest.raises(DeckError, match="/digest"):
        write_deck(tmp_path, "x", tmp_path, FakeLLM(), load_config(REPO_ROOT))


def test_client_claims_must_come_from_rfp() -> None:
    from studio.deck.writer import Fact, unsupported_client_claims

    facts = [Fact("Care managers review claims manually in a legacy portal")]
    items = ["Care managers review claims manually", "Leadership seeks AI governance frameworks"]
    assert unsupported_client_claims(items, facts) == [
        "not supported by the RFP facts: 'Leadership seeks AI governance frameworks'"
    ]


def test_filled_placeholder_flag() -> None:
    from studio.deck.writer import filled_placeholder_flags

    block = _block("ns-1", "next_steps", "Plan", ["Pilot, go/no-go review on {{date}}"])
    flags = filled_placeholder_flags("go/no-go review on March 15, 2027", [block])
    assert flags == ["a block's {{date}} may have been filled with March 15, 2027: check"]
    assert filled_placeholder_flags("go/no-go review", [block]) == []
