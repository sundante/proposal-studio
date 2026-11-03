import json

import pytest
from pydantic import TypeAdapter, ValidationError

from studio.config import LayoutMapConfig, Limits
from studio.deck.schemas import (
    SLIDE_TYPES,
    ArchitectureSlide,
    BulletSlide,
    Deck,
    MaturitySlide,
    Slide,
    TitleSlide,
    check_limits,
    model_for,
    slide_model,
)
from tests.conftest import SAMPLE_DECK


def test_sample_deck_covers_every_slide_type() -> None:
    deck = Deck.model_validate_json(SAMPLE_DECK.read_text())
    assert [s.slide_type for s in deck.slides] == list(SLIDE_TYPES)
    assert isinstance(deck.slides[0], TitleSlide)
    assert isinstance(deck.slides[1], BulletSlide)
    assert isinstance(deck.slides[3], ArchitectureSlide)
    assert isinstance(deck.slides[7], MaturitySlide)
    assert all(not check_limits(s, Limits()) for s in deck.slides)


def test_discriminator_and_unknown_type() -> None:
    adapter = TypeAdapter(Slide)
    slide = adapter.validate_python(
        {"id": "w", "slide_type": "why_us", "title": "Why", "bullets": []}
    )
    assert isinstance(slide, BulletSlide)
    with pytest.raises(ValidationError):
        adapter.validate_python({"id": "x", "slide_type": "nope", "title": "?"})
    with pytest.raises(ValueError):
        model_for("nope")


def test_check_limits_flags_lengths_and_counts() -> None:
    slide = BulletSlide(
        id="u", slide_type="understanding", title="T" * 80, bullets=["b" * 120] + ["ok"] * 5
    )
    issues = {(i.field, i.kind) for i in check_limits(slide, Limits())}
    assert {("title", "too_long"), ("bullets[1]", "too_long"), ("bullets", "too_many")} <= issues
    few = BulletSlide(id="u", slide_type="understanding", title="T", bullets=["one"])
    assert [i.kind for i in check_limits(few, Limits())] == ["too_few"]
    arch = ArchitectureSlide(id="a", title="A", layers=[])
    assert [i.kind for i in check_limits(arch, Limits())] == ["too_few"]


def test_slide_model_schema_constraints() -> None:
    limits = Limits(title=60, bullet=90, min_bullets=2, max_bullets=4)
    schema = slide_model("platform", limits).model_json_schema()
    assert schema["properties"]["title"]["maxLength"] == 60
    bullets = schema["properties"]["bullets"]
    assert bullets["minItems"] == 2 and bullets["maxItems"] == 4
    assert bullets["items"]["maxLength"] == 90
    arch = json.dumps(slide_model("solution_architecture", limits).model_json_schema())
    assert '"maxLength": 40' in arch  # component limit
    for slide_type in SLIDE_TYPES:
        slide_model(slide_type, limits)
    with pytest.raises(ValueError):
        slide_model("nope", limits)


def test_per_type_limit_overrides() -> None:
    cfg = LayoutMapConfig.model_validate(
        {
            "template": "t.pptx",
            "layouts": {"why_us": {"layout": "X", "limits": {"bullet": 60, "max_bullets": 3}}},
        }
    )
    assert cfg.limits_for("why_us").bullet == 60 and cfg.limits_for("why_us").max_bullets == 3
    assert cfg.limits_for("platform").bullet == 110
    with pytest.raises(ValidationError):
        LayoutMapConfig.model_validate(
            {"template": "t", "layouts": {"x": {"layout": "X", "limits": {"bogus": 1}}}}
        )
