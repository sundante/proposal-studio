import pytest

from studio.config import StorylineConfig, load_config
from studio.deck.storyline import (
    OutlineError,
    build_outline,
    evaluate,
    load_outline,
    parse_rule,
    render_outline,
    save_outline,
    toggle,
)
from tests.conftest import REPO_ROOT
from tests.test_digest import sample_digest


def test_parse_rules() -> None:
    assert str(parse_rule("compliance contains HITRUST")) == "compliance contains HITRUST"
    assert parse_rule("risks_and_red_flags not empty").op == "not_empty"
    assert parse_rule("requirements count >= 10").value == "10"
    for bad in ("compliance has HITRUST", "nonsense contains x", "requirements count > 3"):
        with pytest.raises(OutlineError, match="Invalid include_if rule"):
            parse_rule(bad)


def test_evaluate_with_citation() -> None:
    digest = sample_digest()
    ok, why = evaluate(parse_rule("compliance contains hipaa"), digest)
    assert ok and why == "rule matched: compliance contains hipaa [2 Submission, p.1]"
    assert evaluate(parse_rule("compliance contains HITRUST"), digest)[0] is False
    assert evaluate(parse_rule("requirements count >= 2"), digest)[0] is True
    assert evaluate(parse_rule("requirements count >= 3"), digest)[0] is False
    assert evaluate(parse_rule("open_questions not empty"), digest)[0] is True


def test_default_storyline_outline() -> None:
    cfg = load_config(REPO_ROOT).storyline
    outline = build_outline(cfg, sample_digest(), "acme")
    by_id = {s.id: s for s in outline.slides}
    assert by_id["title"].reason == "required"
    assert by_id["governance"].included  # HIPAA rule (OR with HITRUST)
    assert "compliance contains HIPAA" in by_id["governance"].reason
    assert by_id["why_us"].included and "optional (no rule)" in by_id["why_us"].reason
    assert "Next: `/deck`" in render_outline(outline)


def test_rule_not_matched_excludes() -> None:
    cfg = StorylineConfig.model_validate(
        {
            "slides": [
                {
                    "id": "gov",
                    "slide_type": "governance",
                    "required": False,
                    "include_if": ["compliance contains SOC2"],
                }
            ]
        }
    )
    [slide] = build_outline(cfg, sample_digest(), "acme").slides
    assert not slide.included and slide.reason.startswith("no rule matched")


def test_toggles_persist_and_required_protected(tmp_path) -> None:
    cfg = load_config(REPO_ROOT).storyline
    outline = toggle(build_outline(cfg, sample_digest(), "acme"), "why_us", False)
    save_outline(tmp_path, outline)
    rebuilt = build_outline(cfg, sample_digest(), "acme", load_outline(tmp_path))
    why = next(s for s in rebuilt.slides if s.id == "why_us")
    assert not why.included and why.toggled and why.reason == "toggled off by you"
    with pytest.raises(OutlineError, match="required"):
        toggle(rebuilt, "title", False)
    with pytest.raises(OutlineError, match="No slide 'nope'"):
        toggle(rebuilt, "nope", True)
