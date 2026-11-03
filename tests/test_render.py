import time
from pathlib import Path

import pytest
from pptx import Presentation

from studio import config as cfgmod
from studio.config import LayoutMapConfig
from studio.deck.schemas import BulletSlide, Deck
from studio.render.renderer import render, truncate
from tests.conftest import REPO_ROOT, SAMPLE_DECK


@pytest.fixture
def cfg() -> LayoutMapConfig:
    return cfgmod.load_config(REPO_ROOT).layout_map


@pytest.fixture
def deck() -> Deck:
    return Deck.model_validate_json(SAMPLE_DECK.read_text())


def test_sample_deck_renders_clean(deck, cfg, sample_template: Path, tmp_path: Path) -> None:
    start = time.perf_counter()
    report = render(deck, cfg, sample_template, tmp_path, "acme-demo")
    assert time.perf_counter() - start < 10
    qa = report.qa
    assert qa.ok and qa.slide_count == 11, qa.to_markdown()
    assert not (qa.truncated or qa.empty_placeholders or qa.missing_provenance or qa.warnings)
    assert report.path == tmp_path / "acme-demo-v1.pptx"

    prs = Presentation(str(report.path))
    assert len(prs.slides) == 11  # template's 2 sample slides removed
    assert prs.slides[0].shapes.title.text == deck.slides[0].title
    width, height = prs.slide_width, prs.slide_height
    for slide in prs.slides:
        for shape in slide.shapes:
            assert shape.left + shape.width <= width and shape.top + shape.height <= height
            if shape.is_placeholder:
                assert shape.text_frame.text.strip(), "empty placeholder left on slide"
    notes = prs.slides[1].notes_slide.notes_text_frame.text
    assert "Sources: [1 Introduction > 1.1 Background, p.1]" in notes
    arch = prs.slides[3]
    layers = deck.slides[3].layers
    boxes = [s for s in arch.shapes if not s.is_placeholder]
    assert len(boxes) == len(layers) + sum(len(layer.components) for layer in layers)
    stages = [p.text for p in prs.slides[7].placeholders[1].text_frame.paragraphs]
    assert stages[0].startswith("Foundation — ")


def test_versions_never_overwrite(deck, cfg, sample_template: Path, tmp_path: Path) -> None:
    first = render(deck, cfg, sample_template, tmp_path, "acme").path
    second = render(deck, cfg, sample_template, tmp_path, "acme").path
    assert (first.name, second.name) == ("acme-v1.pptx", "acme-v2.pptx")


def test_truncation_and_trimming_are_reported(cfg, sample_template: Path, tmp_path: Path) -> None:
    long_bullet = "Word " * 40
    deck = Deck(
        opportunity="acme",
        slides=[
            BulletSlide(
                id="why_us",
                slide_type="why_us",
                title="Why us",
                bullets=[long_bullet, "two", "three", "four", "five", "six"],
                sources=["block:x"],
            )
        ],
    )
    report = render(deck, cfg, sample_template, tmp_path, "acme")
    assert report.qa.ok
    assert report.qa.truncated == ["why_us.bullets[1]: 200 → 105 chars"]  # cut at a word
    assert "kept the first 5 of 6 items" in report.qa.warnings[0]
    paras = Presentation(str(report.path)).slides[0].placeholders[1].text_frame.paragraphs
    assert len(paras) == 5 and paras[0].text.endswith("…") and len(paras[0].text) <= 110


def test_mapping_errors_and_missing_provenance(cfg, sample_template: Path, tmp_path: Path) -> None:
    bad_cfg = cfg.model_copy(deep=True)
    del bad_cfg.layouts["why_us"]
    bad_cfg.layouts["platform"].layout = "Firm Layout 7"
    slides = [
        BulletSlide(id="why_us", slide_type="why_us", title="Why", bullets=["a", "b", "c"]),
        BulletSlide(id="platform", slide_type="platform", title="P", bullets=["a", "b", "c"]),
        BulletSlide(id="gov", slide_type="governance", title="G", bullets=["a", "b", "c"]),
    ]
    report = render(Deck(opportunity="x", slides=slides), bad_cfg, sample_template, tmp_path, "x")
    errors = " ".join(report.qa.errors)
    assert "no layout mapped for slide type 'why_us'" in errors
    assert "layout 'Firm Layout 7' isn't in the template" in errors and "'Comparison'" in errors
    assert report.qa.slide_count == 1
    assert report.qa.missing_provenance == ["gov"]


def test_missing_template_is_an_error(deck, cfg, tmp_path: Path) -> None:
    report = render(deck, cfg, tmp_path / "nope.pptx", tmp_path, "x")
    assert report.path is None and "Template not found" in report.qa.errors[0]


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [("short", 10, "short"), ("one two three four", 12, "one two…"), ("abcdefghij", 5, "abcd…")],
)
def test_truncate(text: str, limit: int, expected: str) -> None:
    assert truncate(text, limit) == expected
