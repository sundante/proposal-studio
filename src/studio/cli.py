"""`studio` CLI: mirrors the chat commands so every route can be tested without Open WebUI."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import typer
import yaml

from studio import __version__, ingest, rag, session
from studio import config as cfgmod
from studio.llm import LLMClient, LLMError, OllamaClient, model_is_pulled
from studio.rag import VectorIndex

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


# --- opportunities, ingest, ask -------------------------------------------------------------


def get_llm() -> LLMClient:
    """The LLM backend for CLI commands (tests monkeypatch this)."""
    return OllamaClient(cfgmod.load_config().models, on_status=_status)


def _status(message: str) -> None:
    typer.echo(f"… {message}", err=True)


def _session() -> tuple[Path, session.SessionStore, session.Session]:
    root = cfgmod.project_root()
    store = session.SessionStore(root)
    return root, store, store.load(os.environ.get("STUDIO_SESSION", "cli"))


def _next(hint: str) -> None:
    typer.echo(f"\nNext: {hint}")


@app.command()
def new(
    opp_id: str, title: str = typer.Argument("", help="Optional human-readable title.")
) -> None:
    """Create an opportunity workspace and make it active."""
    root, store, sess = _session()
    try:
        opp = session.create_opportunity(root, opp_id, title)
    except session.SessionError as exc:
        _fail(str(exc))
    sess.active_opp = opp.id
    store.save(sess)
    typer.echo(f"Created {opp.id} at {opp.path} (now active).")
    _next(f"`studio ingest <files>` or drop RFP files into {opp.path / 'input'}")


@app.command()
def use(opp_id: str = typer.Argument(None, help="Opportunity to switch to; omit to list.")) -> None:
    """Switch the active opportunity, or list opportunities."""
    root, store, sess = _session()
    if not opp_id:
        opps = session.list_opportunities(root)
        if not opps:
            typer.echo("No opportunities yet.")
            _next("`studio new <opp-id> [title]`")
            return
        for opp in opps:
            mark = "*" if opp.id == sess.active_opp else " "
            typer.echo(f"{mark} {opp.id}  {opp.title}")
        return
    try:
        opp = session.get_opportunity(root, opp_id)
    except session.SessionError as exc:
        _fail(str(exc))
    sess.active_opp = opp.id
    store.save(sess)
    typer.echo(f"Active opportunity: {opp.id}")
    _next("`studio status`")


@app.command("ingest")
def ingest_cmd(
    files: list[Path] = typer.Argument(  # noqa: B008 - typer's documented pattern
        None, help="Files or folders; omit to ingest input/."
    ),
    yes: bool = typer.Option(False, "--yes", help="Continue even if possible PHI is found."),
    opp: str = typer.Option(None, "--opp", help="Opportunity id (default: active)."),
) -> None:
    """Ingest RFP files into the opportunity and build its index."""
    root, _store, sess = _session()
    try:
        cfg = cfgmod.load_config()
        opportunity = session.active_opportunity(root, sess, opp)
        report = ingest.ingest(
            opportunity.path,
            files or [],
            get_llm(),
            cfg.rag,
            cfg.models.roles["embed"].model,
            confirm_phi=yes,
            on_status=_status,
        )
    except (cfgmod.ConfigError, session.SessionError, ingest.IngestError, LLMError) as exc:
        _fail(str(exc))

    if report.blocked:
        typer.echo("Possible PHI found (RFPs should not contain PHI). Nothing was ingested:")
        for hit in report.phi_hits:
            where = f"{hit.file}" + (f", p.{hit.page}" if hit.page else "")
            typer.echo(f"  - {where}: {hit.kind} ({hit.excerpt})")
        typer.echo("Check the files, then re-run with --yes to ingest anyway.")
        raise typer.Exit(2)

    for label, names in (
        ("new", report.new),
        ("changed", report.changed),
        ("unchanged", report.unchanged),
        ("removed", report.removed),
    ):
        if names:
            typer.echo(f"{label}: {', '.join(names)}")
    for name, reason in report.skipped.items():
        typer.echo(f"skipped {name}: {reason}")
    if report.phi_hits:
        typer.echo(f"Warning: ingested despite {len(report.phi_hits)} possible PHI matches.")
    typer.echo(f"Indexed {report.chunks_added} new chunks ({report.total_chunks} total).")
    _next('`studio ask "<question>"` or `studio digest`')


@app.command()
def ask(
    question: str,
    opp: str = typer.Option(None, "--opp", help="Opportunity id (default: active)."),
    top_k: int = typer.Option(None, "--top-k", min=1, max=50, help="Chunks to retrieve."),
) -> None:
    """Answer a question from the active RFP, with citations."""
    root, _store, sess = _session()
    try:
        cfg = cfgmod.load_config()
        opportunity = session.active_opportunity(root, sess, opp)
        index = VectorIndex(opportunity.path / "index")
        if not len(index):
            _fail(f"Nothing ingested for {opportunity.id} yet. Run `studio ingest <files>`.")
        for piece in rag.answer(
            question, index, get_llm(), cfg.rag, top_k=top_k, on_status=_status
        ):
            typer.echo(piece, nl=False)
        typer.echo()
    except (cfgmod.ConfigError, session.SessionError, LLMError) as exc:
        _fail(str(exc))
    _next('another `studio ask "…"`, or `studio digest`')


@app.command()
def status(
    opp: str = typer.Option(None, "--opp", help="Opportunity id (default: active)."),
) -> None:
    """Show the active opportunity's pipeline status and the loaded model."""
    root, _store, sess = _session()
    try:
        opportunity = session.active_opportunity(root, sess, opp)
    except session.SessionError as exc:
        _fail(str(exc))
    info = session.opportunity_status(opportunity)
    typer.echo(f"Opportunity: {info['id']}" + (f" — {info['title']}" if info["title"] else ""))
    if info["files"]:
        typer.echo(f"Ingested: {len(info['files'])} files, {info['chunks']} chunks")
        for name, count in info["files"].items():
            typer.echo(f"  - {name} ({count} chunks)")
    else:
        typer.echo("Ingested: nothing yet")
    for key in ("digest", "outline", "deck"):
        typer.echo(f"{key.capitalize()}: {'yes' if info[key] else 'no'}")
    typer.echo(f"Renders: {', '.join(info['renders']) or 'none'}")
    try:
        loaded = OllamaClient(cfgmod.load_config().models).loaded_models()
        typer.echo(f"Loaded model: {', '.join(loaded) or 'none'}")
    except (cfgmod.ConfigError, LLMError, httpx.HTTPError):
        typer.echo("Loaded model: unknown (Ollama not reachable)")
    if not info["files"]:
        _next("`studio ingest <files>`")
    elif not info["digest"]:
        _next('`studio ask "<question>"` or `studio digest`')


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
