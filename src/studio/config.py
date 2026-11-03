"""Load and validate the YAML config (base files + ``config/overrides.yaml``).

The project root is ``$STUDIO_HOME`` if set, else the current working directory. Base YAML files
are never edited; runtime changes from ``/config set`` go to ``config/overrides.yaml``.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from studio.guards import GuardError, check_model_allowed

SECTIONS = ("models", "routes", "agents", "storyline", "layout_map", "rag", "deck", "research")
OVERRIDES_FILE = "overrides.yaml"


class ConfigError(ValueError):
    """Raised for invalid config files or rejected ``/config set`` changes."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- models.yaml ----------------------------------------------------------------------------


class RoleConfig(_Strict):
    """Model settings for one role (router, worker, embed)."""

    model: str
    num_ctx: int | None = Field(default=None, gt=0, le=131072)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    num_gpu: int | None = Field(default=None, ge=0)  # 0 = CPU only (Ollama option)


class ModelsConfig(_Strict):
    """Model registry: Ollama endpoint and one model per role."""

    ollama_url: str = "http://localhost:11434"
    roles: dict[str, RoleConfig]
    keep_alive: str = "10m"
    block_cloud_models: bool = True
    think: bool = False
    timeout_s: float = Field(default=600, gt=0)

    @model_validator(mode="after")
    def _check_roles(self) -> ModelsConfig:
        missing = {"router", "worker", "embed"} - self.roles.keys()
        if missing:
            raise ValueError(f"missing roles: {', '.join(sorted(missing))}")
        for role in self.roles.values():
            try:
                check_model_allowed(role.model, block_cloud=self.block_cloud_models)
            except GuardError as exc:
                raise ValueError(str(exc)) from exc
        return self


# --- routes.yaml ----------------------------------------------------------------------------


class CommandSpec(_Strict):
    """One chat command."""

    route: str
    help: str = ""


class RouteExample(_Strict):
    """Few-shot example for the classifier."""

    text: str
    route: str


class RoutesConfig(_Strict):
    """Commands, aliases, auto-route keywords and thresholds."""

    auto_route: bool = True
    auto_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    confirm_routes: list[str] = Field(default_factory=list)
    commands: dict[str, CommandSpec]
    aliases: dict[str, str] = Field(default_factory=dict)
    keywords: dict[str, list[str]] = Field(default_factory=dict)
    examples: list[RouteExample] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_aliases(self) -> RoutesConfig:
        unknown = {a: c for a, c in self.aliases.items() if c not in self.commands}
        if unknown:
            raise ValueError(f"aliases point to unknown commands: {unknown}")
        return self


# --- agents.yaml ----------------------------------------------------------------------------


class AgentSpec(_Strict):
    """Headless agent CLI adapter definition (flags verified per CLI; see DECISIONS.md)."""

    label: str
    plan_cmd: list[str]
    apply_cmd: list[str]
    env: dict[str, str] = Field(default_factory=dict)
    files: dict[str, str] = Field(default_factory=dict)  # written into the working copy
    model: str
    enabled: bool = True
    note: str = ""  # shown when the agent is disabled or limited


DEFAULT_ENV_ALLOWLIST = [
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "TERM",
    "NODE_OPTIONS",
]


class AgentsConfig(_Strict):
    """Agent CLI adapters and sandbox settings."""

    sandbox_root: str = "workspace/{opp}/agent"
    default_timeout_s: int = Field(default=900, gt=0)
    copy_in: list[str] = Field(default_factory=lambda: ["deck.json", "digest.json", "outline.json"])
    env_allowlist: list[str] = Field(default_factory=lambda: list(DEFAULT_ENV_ALLOWLIST))
    agents: dict[str, AgentSpec] = Field(default_factory=dict)


# --- storyline.yaml / layout_map.yaml -------------------------------------------------------


class StorySlide(_Strict):
    """One slide in the deck spine."""

    id: str
    slide_type: str
    required: bool = True
    include_if: list[str] = Field(default_factory=list)
    max_items: int | None = Field(default=None, gt=0)


class StorylineConfig(_Strict):
    """Fixed deck spine with optional slides."""

    slides: list[StorySlide]


class Limits(_Strict):
    """Hard text limits for slide fields (characters / item counts)."""

    title: int = Field(default=70, gt=0)
    subtitle: int = Field(default=120, gt=0)
    bullet: int = Field(default=110, gt=0)
    min_bullets: int = Field(default=3, ge=0)
    max_bullets: int = Field(default=5, gt=0)
    layer: int = Field(default=30, gt=0)
    component: int = Field(default=40, gt=0)
    max_layers: int = Field(default=6, gt=0)
    max_components: int = Field(default=6, gt=0)
    notes: int = Field(default=2000, gt=0)

    @model_validator(mode="after")
    def _check_counts(self) -> Limits:
        if self.min_bullets > self.max_bullets:
            raise ValueError("min_bullets must not exceed max_bullets")
        return self


class DiagramArea(_Strict):
    """Box (inches from the top-left) the architecture diagram is drawn in."""

    left: float = Field(ge=0)
    top: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class LayoutSpec(_Strict):
    """How one slide_type maps onto a template layout."""

    layout: str
    placeholders: dict[str, int | str] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)
    diagram_area: DiagramArea | None = None

    @model_validator(mode="after")
    def _check_limit_keys(self) -> LayoutSpec:
        unknown = set(self.limits) - set(Limits.model_fields)
        if unknown:
            raise ValueError(f"unknown limit keys: {', '.join(sorted(unknown))}")
        return self


class LayoutMapConfig(_Strict):
    """Template path, text limits and slide_type → layout + placeholder mapping."""

    template: str
    remove_existing_slides: bool = True
    limits: Limits = Field(default_factory=Limits)
    layouts: dict[str, LayoutSpec] = Field(default_factory=dict)

    def limits_for(self, slide_type: str) -> Limits:
        """Global limits with the slide type's overrides applied."""
        spec = self.layouts.get(slide_type)
        if not spec or not spec.limits:
            return self.limits
        return Limits.model_validate({**self.limits.model_dump(), **spec.limits})


# --- rag.yaml -------------------------------------------------------------------------------


class RagConfig(_Strict):
    """Chunking and retrieval settings."""

    chunk_tokens: int = Field(default=800, ge=100, le=4000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)
    top_k: int = Field(default=6, ge=1, le=50)
    min_score: float = Field(default=0.25, ge=-1.0, le=1.0)
    digest_group_tokens: int = Field(default=2000, ge=200, le=8000)
    dedupe_similarity: float = Field(default=0.9, ge=0.5, le=1.0)

    @model_validator(mode="after")
    def _check_overlap(self) -> RagConfig:
        if self.chunk_overlap >= self.chunk_tokens:
            raise ValueError("chunk_overlap must be smaller than chunk_tokens")
        return self


# --- deck.yaml ------------------------------------------------------------------------------


class DeckConfig(_Strict):
    """Block harvest and deck-writer settings."""

    blocks_per_slide: int = Field(default=3, ge=2, le=4)
    min_block_score: float = Field(default=0.2, ge=-1.0, le=1.0)
    harvest_min_chars: int = Field(default=80, ge=0)
    include_flagged_blocks: bool = False  # use blocks marked needs_review when writing


# --- research.yaml --------------------------------------------------------------------------


class ResearchConfig(_Strict):
    """Offline research settings."""

    max_llm_calls: int = Field(default=12, ge=3, le=40)
    max_sub_questions: int = Field(default=5, ge=1, le=8)
    top_k_per_query: int = Field(default=4, ge=1, le=20)
    excerpts_per_question: int = Field(default=6, ge=1, le=20)
    weak_score: float = Field(default=0.35, ge=-1.0, le=1.0)
    sources: list[Literal["rfp", "proposals", "reference"]] = Field(
        default_factory=lambda: ["rfp", "proposals", "reference"], min_length=1
    )


class StudioConfig(_Strict):
    """The effective configuration: all sections merged with overrides."""

    models: ModelsConfig
    routes: RoutesConfig
    agents: AgentsConfig
    storyline: StorylineConfig
    layout_map: LayoutMapConfig
    rag: RagConfig = Field(default_factory=RagConfig)
    deck: DeckConfig = Field(default_factory=DeckConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)

    @model_validator(mode="after")
    def _check_agent_models(self) -> StudioConfig:
        for name, agent in self.agents.agents.items():
            try:
                check_model_allowed(agent.model, block_cloud=self.models.block_cloud_models)
            except GuardError as exc:
                raise ValueError(f"agent '{name}': {exc}") from exc
        return self


# --- loading --------------------------------------------------------------------------------


def project_root() -> Path:
    """Project root: ``$STUDIO_HOME`` or the current working directory."""
    return Path(os.environ.get("STUDIO_HOME") or Path.cwd()).resolve()


def config_dir(root: Path | None = None) -> Path:
    """Directory holding the YAML config files."""
    return (root or project_root()) / "config"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a mapping at the top level.")
    return data


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_base(root: Path | None = None) -> dict[str, Any]:
    """Raw base config (no overrides) as ``{section: dict}``."""
    cdir = config_dir(root)
    return {section: _read_yaml(cdir / f"{section}.yaml") for section in SECTIONS}


def load_overrides(root: Path | None = None) -> dict[str, Any]:
    """Raw overrides from ``config/overrides.yaml``."""
    return _read_yaml(config_dir(root) / OVERRIDES_FILE)


def _validate(raw: dict[str, Any]) -> StudioConfig:
    try:
        return StudioConfig.model_validate(raw)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigError(f"Invalid config: {errors}") from exc


def load_config(root: Path | None = None) -> StudioConfig:
    """Load base YAML + overrides and validate. Raises :class:`ConfigError` on problems."""
    return _validate(_deep_merge(load_base(root), load_overrides(root)))


# --- /config set | reset --------------------------------------------------------------------


def resolve_key(key: str, effective: dict[str, Any]) -> list[str]:
    """Turn a user key into a full path. ``worker.model`` → ``models.roles.worker.model``.

    Tries, in order: the key as given, then under ``models.``, ``models.roles.``, ``routes.``,
    ``rag.``.
    Only paths that already exist in the effective config are accepted (no new keys).
    """
    parts = [p for p in key.strip().split(".") if p]
    if not parts:
        raise ConfigError("Empty config key.")
    shorthand = ([], ["models"], ["models", "roles"], ["routes"], ["rag"], ["deck"], ["research"])
    for prefix in shorthand:
        path = prefix + parts
        node: Any = effective
        for part in path:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                break
        else:
            return path
    raise ConfigError(f"Unknown config key '{key}'. Run `/config` to see valid keys.")


def set_value(key: str, value: str, root: Path | None = None) -> StudioConfig:
    """Validate and persist one override. ``value`` is parsed as YAML (``0.5``, ``true``, …).

    Returns the new effective config. Base YAML files are never modified.
    """
    root = root or project_root()
    base, overrides = load_base(root), load_overrides(root)
    effective = _deep_merge(base, overrides)
    path = resolve_key(key, effective)
    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError:
        parsed = value
    if parsed is None:
        parsed = value

    patch: dict[str, Any] = {}
    node = patch
    for part in path[:-1]:
        node = node.setdefault(part, {})
    node[path[-1]] = parsed

    new_overrides = _deep_merge(overrides, patch)
    cfg = _validate(_deep_merge(base, new_overrides))
    out = config_dir(root) / OVERRIDES_FILE
    out.write_text(yaml.safe_dump(new_overrides, sort_keys=False), encoding="utf-8")
    return cfg


def reset(root: Path | None = None) -> StudioConfig:
    """Delete ``config/overrides.yaml`` and return the base config."""
    (config_dir(root) / OVERRIDES_FILE).unlink(missing_ok=True)
    return load_config(root)
