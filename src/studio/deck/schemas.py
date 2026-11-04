"""Pydantic models per slide type, the ``Deck`` model, and text-limit checks.

The models here are lenient so any ``deck.json`` loads; limits from ``layout_map.yaml`` are
checked with :func:`check_limits` (and enforced by the renderer). :func:`slide_model` builds a
strict copy with ``max_length`` constraints for use as the deck writer's LLM schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model

from studio.config import Limits

BULLET_TYPES = (
    "understanding",
    "ai_enablement",
    "platform",
    "governance",
    "practice_leadership",
    "why_us",
)
SLIDE_TYPES = (
    "title",
    "understanding",
    "before_after",
    "solution_architecture",
    "ai_enablement",
    "platform",
    "governance",
    "maturity",
    "practice_leadership",
    "why_us",
    "next_steps",
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlideBase(_Model):
    """Fields every slide has."""

    id: str
    slide_type: str
    title: str
    speaker_notes: str = ""
    sources: list[str] = Field(default_factory=list)  # block ids + digest citations
    review: list[str] = Field(default_factory=list)  # things a human should check


class TitleSlide(SlideBase):
    """Cover: opportunity title and client/date line."""

    slide_type: Literal["title"] = "title"
    subtitle: str = ""


class BulletSlide(SlideBase):
    """Title + 3–5 bullets (understanding, AI enablement, platform, governance, …)."""

    slide_type: Literal[
        "understanding", "ai_enablement", "platform", "governance", "practice_leadership", "why_us"
    ]
    bullets: list[str] = Field(default_factory=list)


class BeforeAfterSlide(SlideBase):
    """Current state → future state."""

    slide_type: Literal["before_after"] = "before_after"
    before_title: str = "Today"
    after_title: str = "With us"
    before: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)


class Layer(_Model):
    """One architecture layer and its components."""

    name: str
    components: list[str] = Field(default_factory=list)


class ArchitectureSlide(SlideBase):
    """Text-based layered architecture (drawn as boxes)."""

    slide_type: Literal["solution_architecture"] = "solution_architecture"
    layers: list[Layer] = Field(default_factory=list)


class Stage(_Model):
    """One maturity stage."""

    name: str
    description: str


class MaturitySlide(SlideBase):
    """Roadmap / maturity model."""

    slide_type: Literal["maturity"] = "maturity"
    stages: list[Stage] = Field(default_factory=list)


class Step(_Model):
    """One engagement step."""

    when: str
    what: str


class NextStepsSlide(SlideBase):
    """Engagement plan / timeline."""

    slide_type: Literal["next_steps"] = "next_steps"
    steps: list[Step] = Field(default_factory=list)


Slide = Annotated[
    TitleSlide
    | BulletSlide
    | BeforeAfterSlide
    | ArchitectureSlide
    | MaturitySlide
    | NextStepsSlide,
    Field(discriminator="slide_type"),
]


class Deck(_Model):
    """The whole deck as written to ``deck.json``."""

    opportunity: str
    client: str | None = None
    generated: str | None = None
    slides: list[Slide] = Field(default_factory=list)


def model_for(slide_type: str) -> type[SlideBase]:
    """The lenient model class for a slide type."""
    if slide_type in BULLET_TYPES:
        return BulletSlide
    models: dict[str, type[SlideBase]] = {
        "title": TitleSlide,
        "before_after": BeforeAfterSlide,
        "solution_architecture": ArchitectureSlide,
        "maturity": MaturitySlide,
        "next_steps": NextStepsSlide,
    }
    try:
        return models[slide_type]
    except KeyError as exc:
        raise ValueError(f"Unknown slide type '{slide_type}'.") from exc


# --- limits ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class LimitIssue:
    """A field that breaks a limit. ``kind`` is ``too_long``, ``too_many`` or ``too_few``."""

    slide_id: str
    field: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.slide_id}.{self.field}: {self.detail}"


def list_fields(slide: SlideBase) -> dict[str, list[str]]:
    """List fields rendered one paragraph per item, as display text (bullet-limited).

    Architecture layers are drawn as shapes and checked separately.
    """
    if isinstance(slide, BulletSlide):
        return {"bullets": slide.bullets}
    if isinstance(slide, BeforeAfterSlide):
        return {"before": slide.before, "after": slide.after}
    if isinstance(slide, MaturitySlide):
        return {"stages": [f"{s.name} — {s.description}" for s in slide.stages]}
    if isinstance(slide, NextStepsSlide):
        return {"steps": [f"{s.when} — {s.what}" for s in slide.steps]}
    return {}


def check_limits(slide: SlideBase, limits: Limits) -> list[LimitIssue]:
    """Every limit the slide breaks (text length, item counts)."""
    issues: list[LimitIssue] = []

    def too_long(field: str, text: str, limit: int) -> None:
        if len(text) > limit:
            issues.append(LimitIssue(slide.id, field, "too_long", f"{len(text)} > {limit} chars"))

    too_long("title", slide.title, limits.title)
    too_long("speaker_notes", slide.speaker_notes, limits.notes)
    if isinstance(slide, TitleSlide):
        too_long("subtitle", slide.subtitle, limits.subtitle)
    if isinstance(slide, BeforeAfterSlide):
        too_long("before_title", slide.before_title, limits.title)
        too_long("after_title", slide.after_title, limits.title)
    for field, items in list_fields(slide).items():
        for n, item in enumerate(items, start=1):
            too_long(f"{field}[{n}]", item, limits.bullet)
        if len(items) > limits.max_bullets:
            issues.append(
                LimitIssue(
                    slide.id, field, "too_many", f"{len(items)} items > {limits.max_bullets}"
                )
            )
        elif len(items) < limits.min_bullets:
            issues.append(
                LimitIssue(slide.id, field, "too_few", f"{len(items)} items < {limits.min_bullets}")
            )
    if isinstance(slide, ArchitectureSlide):
        if len(slide.layers) > limits.max_layers:
            issues.append(
                LimitIssue(
                    slide.id,
                    "layers",
                    "too_many",
                    f"{len(slide.layers)} layers > {limits.max_layers}",
                )
            )
        if not slide.layers:
            issues.append(LimitIssue(slide.id, "layers", "too_few", "no layers"))
        for n, layer in enumerate(slide.layers, start=1):
            too_long(f"layers[{n}].name", layer.name, limits.layer)
            for m, comp in enumerate(layer.components, start=1):
                too_long(f"layers[{n}].components[{m}]", comp, limits.component)
            if len(layer.components) > limits.max_components:
                issues.append(
                    LimitIssue(
                        slide.id,
                        f"layers[{n}].components",
                        "too_many",
                        f"{len(layer.components)} > {limits.max_components}",
                    )
                )
    return issues


def slide_model(slide_type: str, limits: Limits, *, enforce: bool = True) -> type[BaseModel]:
    """The content model for ``slide_type`` (no ``id``/``sources``; those are filled in code).

    With ``enforce`` the limits become ``maxLength``/``maxItems`` constraints, for validating
    content. With ``enforce=False`` the shape is the same but unconstrained: the deck writer
    uses that as the LLM schema, because grammar-enforced lengths cut text mid-word.
    """

    def text(max_len: int) -> Any:
        if not enforce:
            return str
        return Annotated[str, StringConstraints(min_length=1, max_length=max_len)]

    def items(item: Any, lo: int, hi: int) -> Any:
        if not enforce:
            return list[item]
        return Annotated[list[item], Field(min_length=lo, max_length=hi)]

    lo, hi = limits.min_bullets, limits.max_bullets
    bullet = text(limits.bullet)
    fields: dict[str, Any] = {"title": (text(limits.title), ...), "speaker_notes": (str, "")}
    name = f"{slide_type.title().replace('_', '')}Content"
    if slide_type == "title":
        fields["subtitle"] = (text(limits.subtitle), ...)
    elif slide_type in BULLET_TYPES:
        fields["bullets"] = (items(bullet, lo, hi), ...)
    elif slide_type == "before_after":
        fields["before"] = (items(bullet, lo, hi), ...)
        fields["after"] = (items(bullet, lo, hi), ...)
    elif slide_type == "solution_architecture":
        layer = create_model(
            "LayerContent",
            __config__=ConfigDict(extra="forbid"),
            name=(text(limits.layer), ...),
            components=(items(text(limits.component), 1, limits.max_components), ...),
        )
        fields["layers"] = (items(layer, 2, limits.max_layers), ...)
    elif slide_type == "maturity":
        stage = create_model(
            "StageContent",
            __config__=ConfigDict(extra="forbid"),
            name=(text(limits.layer), ...),
            description=(text(max(limits.bullet - limits.layer - 3, 20)), ...),
        )
        fields["stages"] = (items(stage, lo, hi), ...)
    elif slide_type == "next_steps":
        step = create_model(
            "StepContent",
            __config__=ConfigDict(extra="forbid"),
            when=(text(limits.layer), ...),
            what=(text(max(limits.bullet - limits.layer - 3, 20)), ...),
        )
        fields["steps"] = (items(step, lo, hi), ...)
    else:
        raise ValueError(f"Unknown slide type '{slide_type}'.")
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)
