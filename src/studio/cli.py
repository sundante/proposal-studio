"""`studio` CLI: mirrors the chat commands so every route can be tested without Open WebUI."""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass

import typer
import yaml

from studio import __version__
from studio import config as cfgmod
from studio.llm import LLMError, OllamaClient, model_is_pulled

app = typer.Typer(help="Proposal Studio: local, offline proposal workbench.", no_args_is_help=True)
config_app = typer.Typer(help="Show or change the effective configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"studio {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version, is_eager=True, help="Show the version and exit."
    ),
) -> None:
    """Proposal Studio command line."""


def _fail(message: str) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(1)


# --- config ---------------------------------------------------------------------------------


@config_app.command("show")
def config_show() -> None:
    """Print the effective config (base YAML + overrides)."""
    try:
        cfg = cfgmod.load_config()
    except cfgmod.ConfigError as exc:
        _fail(str(exc))
    typer.echo(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False).rstrip())


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    """Set KEY to VALUE in config/overrides.yaml (e.g. `worker.model qwen3:4b`)."""
    try:
        cfgmod.set_value(key, value)
    except cfgmod.ConfigError as exc:
        _fail(str(exc))
    typer.echo(f"Set {key} = {value} (saved to config/{cfgmod.OVERRIDES_FILE}).")


@config_app.command("reset")
def config_reset() -> None:
    """Remove all overrides and return to the base config."""
    try:
        cfgmod.reset()
    except cfgmod.ConfigError as exc:
        _fail(str(exc))
    typer.echo("Overrides cleared; using base config.")


# --- doctor ---------------------------------------------------------------------------------


@dataclass
class Check:
    """One doctor checklist line."""

    ok: bool
    label: str
    fix: str = ""


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in version.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def run_checks(client: OllamaClient | None = None) -> list[Check]:
    """Run the environment checks behind `studio doctor`."""
    checks = [
        Check(
            sys.version_info >= (3, 11),
            f"Python {sys.version.split()[0]}",
            "Install Python 3.11 or newer.",
        )
    ]
    try:
        cfg = cfgmod.load_config()
        checks.append(Check(True, "Config valid"))
    except cfgmod.ConfigError as exc:
        checks.append(Check(False, "Config valid", str(exc)))
        return checks

    workspace = cfgmod.project_root() / "workspace"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=workspace):
            pass
        checks.append(Check(True, f"Workspace writable ({workspace})"))
    except OSError as exc:
        checks.append(Check(False, f"Workspace writable ({workspace})", str(exc)))

    client = client or OllamaClient(cfg.models)
    try:
        version = client.version()
        pulled = client.list_models()
    except LLMError as exc:
        checks.append(Check(False, f"Ollama reachable at {cfg.models.ollama_url}", str(exc)))
        return checks
    checks.append(Check(True, f"Ollama {version} reachable at {cfg.models.ollama_url}"))
    checks.append(
        Check(
            _version_tuple(version) >= (0, 5),
            "Ollama supports JSON-schema structured output (>= 0.5)",
            "Upgrade Ollama to 0.5 or newer.",
        )
    )
    for role, rc in cfg.models.roles.items():
        checks.append(
            Check(
                model_is_pulled(rc.model, pulled),
                f"Model for {role}: {rc.model}",
                f"Run `ollama pull {rc.model}`.",
            )
        )
    return checks


@app.command()
def doctor() -> None:
    """Check Python, config, workspace, Ollama and the configured models."""
    checks = run_checks()
    for c in checks:
        mark = "[x]" if c.ok else "[ ]"
        typer.echo(f"{mark} {c.label}" + ("" if c.ok else f"  -> {c.fix}"))
    if not all(c.ok for c in checks):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
