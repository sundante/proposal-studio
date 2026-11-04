"""`studio` CLI: mirrors the chat commands so every route can be tested without Open WebUI."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import typer
import yaml

from studio import __version__, ingest, rag, session, views
from studio import blocks as blockmod
from studio import config as cfgmod
from studio import digest as digestmod
from studio import research as researchmod
from studio.deck import storyline, writer
from studio.deck.schemas import Deck
from studio.llm import LLMClient, LLMError, OllamaClient, model_is_pulled
from studio.rag import VectorIndex
from studio.render import inspect_template as inspector
from studio.render.renderer import render as render_deck
from studio.render.sample_template import build_sample_template

app = typer.Typer(help="Proposal Studio: local, offline proposal workbench.", no_args_is_help=True)
config_app = typer.Typer(help="Show or change the effective configuration.", no_args_is_help=True)
app.add_typer(config_app, name="config")
library_app = typer.Typer(help="Index the local library for /research.", no_args_is_help=True)
app.add_typer(library_app, name="library")
owui_app = typer.Typer(
    help="Open WebUI helpers (prompts, automated install).", no_args_is_help=True
)
app.add_typer(owui_app, name="owui")
template_app = typer.Typer(help="Inspect templates and build the sample.", no_args_is_help=True)
app.add_typer(template_app, name="template")


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


def loaded_models() -> list[str] | None:
    """Models loaded in Ollama, or None if it isn't reachable."""
    try:
        return OllamaClient(cfgmod.load_config().models).loaded_models()
    except (cfgmod.ConfigError, LLMError, httpx.HTTPError):
        return None


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
    files: list[Path] = typer.Argument(None, help="Files or folders; omit to ingest input/."),
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
        typer.echo(views.phi_blocked_text(report))
        typer.echo("Check the files, then re-run with --yes to ingest anyway.")
        raise typer.Exit(2)
    typer.echo(views.ingest_report_text(report))
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
    typer.echo(views.status_text(info, loaded_models()))
    _next(views.status_next(info).replace("`/", "`studio "))


@app.command("digest")
def digest_cmd(
    opp: str = typer.Option(None, "--opp", help="Opportunity id (default: active)."),
    xlsx: bool = typer.Option(False, "--xlsx", help="Also export a requirements matrix (XLSX)."),
    show: bool = typer.Option(False, "--show", help="Show the saved digest; don't rebuild."),
) -> None:
    """Build (or show) the RFP digest: problems, requirements, criteria, compliance, risks."""
    root, _store, sess = _session()
    warnings: list[str] = []
    try:
        cfg = cfgmod.load_config()
        opportunity = session.active_opportunity(root, sess, opp)
        if show:
            result = digestmod.load_digest(opportunity.path)
            if result is None:
                _fail(f"No digest for {opportunity.id} yet. Run `studio digest`.")
            if digestmod.is_stale(opportunity.path):
                warnings.append(
                    "Files changed since this digest was built; re-run `studio digest`."
                )
        else:
            report = digestmod.build_digest(opportunity.path, get_llm(), cfg.rag, on_status=_status)
            result, warnings = report.digest, report.warnings
        typer.echo(digestmod.render_summary(result, warnings))
        if xlsx:
            path = digestmod.export_matrix(result, opportunity.path / "out", opportunity.id)
            typer.echo(f"\nRequirements matrix: {path}")
    except (cfgmod.ConfigError, session.SessionError, digestmod.DigestError, LLMError) as exc:
        _fail(str(exc))


# --- blocks, outline, deck -------------------------------------------------------------------


@app.command("harvest")
def harvest_cmd(
    path: Path = typer.Argument(None, help="File or folder (default: library/proposals)."),
    client: list[str] = typer.Option([], "--client", help="Client name(s) to anonymise."),
) -> None:
    """Extract reusable, anonymised blocks from past proposals into library/blocks."""
    root = cfgmod.project_root()
    try:
        cfg = cfgmod.load_config()
        report = blockmod.harvest(
            root, get_llm(), cfg.deck, source=path, clients=client, on_status=_status
        )
    except (cfgmod.ConfigError, blockmod.BlockError, LLMError) as exc:
        _fail(str(exc))
    typer.echo(views.harvest_report_text(report))
    where = blockmod.blocks_dir(root)
    _next(f"review YAML in {where} (set needs_review: false), then `studio blocks`")


@app.command("blocks")
def blocks_cmd(
    query: str = typer.Argument("", help="Search text; omit to list."),
    slide_type: str = typer.Option(None, "--type", help="Only this slide type."),
) -> None:
    """List or search the block library."""
    root = cfgmod.project_root()
    try:
        cfg = cfgmod.load_config()
        if query:
            hits = blockmod.search_blocks(
                root, query, get_llm(), cfg.models.roles["embed"].model, slide_type=slide_type, k=10
            )
        else:
            hits = [
                (b, 0.0) for b in blockmod.load_blocks(root) if slide_type in (None, b.slide_type)
            ]
    except (cfgmod.ConfigError, blockmod.BlockError, LLMError) as exc:
        _fail(str(exc))
    if not hits:
        typer.echo("No blocks yet.")
        _next("`studio harvest`")
        return
    typer.echo(views.blocks_text(hits, show_scores=bool(query)))


def _opp_dir(opp: str | None) -> tuple[Path, Path, str]:
    root, _store, sess = _session()
    opportunity = session.active_opportunity(root, sess, opp)
    return root, opportunity.path, opportunity.id


@app.command("outline")
def outline_cmd(opp: str = typer.Option(None, "--opp", help="Opportunity id.")) -> None:
    """Decide which storyline slides go in the deck (and why)."""
    try:
        cfg = cfgmod.load_config()
        _root, opp_dir, opp_id = _opp_dir(opp)
        digest = digestmod.load_digest(opp_dir)
        if digest is None:
            _fail("No digest yet. Run `studio digest` first.")
        outline = storyline.build_outline(
            cfg.storyline, digest, opp_id, storyline.load_outline(opp_dir)
        )
        storyline.save_outline(opp_dir, outline)
    except (cfgmod.ConfigError, session.SessionError, storyline.OutlineError) as exc:
        _fail(str(exc))
    typer.echo(storyline.render_outline(outline))


@app.command("toggle")
def toggle_cmd(
    slide_id: str,
    state: str = typer.Argument(..., help="on or off"),
    opp: str = typer.Option(None, "--opp", help="Opportunity id."),
) -> None:
    """Turn an optional slide on or off in the outline."""
    if state not in ("on", "off"):
        _fail("Use `on` or `off`.")
    try:
        _root, opp_dir, _opp_id = _opp_dir(opp)
        outline = storyline.load_outline(opp_dir)
        if outline is None:
            _fail("No outline yet. Run `studio outline` first.")
        storyline.save_outline(opp_dir, storyline.toggle(outline, slide_id, state == "on"))
    except (session.SessionError, storyline.OutlineError) as exc:
        _fail(str(exc))
    typer.echo(storyline.render_outline(outline))


def _print_flags(flagged: dict[str, list[str]]) -> None:
    if flagged:
        typer.echo("\n" + views.flags_text(flagged))


@app.command("deck")
def deck_cmd(
    slide_id: str = typer.Argument(None, help="Regenerate only this slide."),
    opp: str = typer.Option(None, "--opp", help="Opportunity id."),
) -> None:
    """Write deck.json by tailoring vetted blocks to the digest (one LLM call per slide)."""
    try:
        cfg = cfgmod.load_config()
        root, opp_dir, opp_id = _opp_dir(opp)
        report = writer.write_deck(
            opp_dir, opp_id, root, get_llm(), cfg, slide_id=slide_id, on_status=_status
        )
    except (cfgmod.ConfigError, session.SessionError, writer.DeckError, LLMError) as exc:
        _fail(str(exc))
    typer.echo(f"Wrote {len(report.written)} slide(s) to {report.path}")
    for slide in report.deck.slides:
        if slide.id in report.written:
            typer.echo("\n" + "\n".join(writer.slide_text(slide)))
    _print_flags(report.flagged)
    _next('`studio render` (or `studio edit <slide_id> "<instruction>"`)')


@app.command("edit")
def edit_cmd(
    slide_id: str,
    instruction: str,
    opp: str = typer.Option(None, "--opp", help="Opportunity id."),
) -> None:
    """Revise one slide following an instruction; shows a before/after diff."""
    try:
        cfg = cfgmod.load_config()
        root, opp_dir, _opp_id = _opp_dir(opp)
        report = writer.edit_slide(
            opp_dir, root, get_llm(), cfg, slide_id, instruction, on_status=_status
        )
    except (cfgmod.ConfigError, session.SessionError, writer.DeckError, LLMError) as exc:
        _fail(str(exc))
    typer.echo(report.diff or "(no change)")
    _print_flags(report.flagged)
    _next("`studio render`")


# --- library and research -------------------------------------------------------------------


@library_app.command("index")
def library_index_cmd(
    collection: str = typer.Argument("all", help="proposals, reference or all."),
    yes: bool = typer.Option(False, "--yes", help="Continue even if possible PHI is found."),
) -> None:
    """Index library/proposals and/or library/reference in place (incremental)."""
    root = cfgmod.project_root()
    names = list(rag.LIBRARY_COLLECTIONS) if collection == "all" else [collection]
    try:
        cfg = cfgmod.load_config()
        llm = get_llm()
        for name in names:
            report = ingest.index_library(
                root,
                name,
                llm,
                cfg.rag,
                cfg.models.roles["embed"].model,
                confirm_phi=yes,
                on_status=_status,
            )
            if report.blocked:
                typer.echo(f"{name}: possible PHI found; nothing indexed. Re-run with --yes:")
                typer.echo(views.phi_hits_text(report.phi_hits))
                raise typer.Exit(2)
            typer.echo(views.library_report_text(name, report))
    except (cfgmod.ConfigError, ingest.IngestError, LLMError) as exc:
        _fail(str(exc))
    _next('`studio research "<question>"`')


@library_app.command("status")
def library_status_cmd() -> None:
    """Show what is indexed in each library collection."""
    typer.echo(views.library_status_text(cfgmod.project_root()))


@app.command("research")
def research_cmd(
    question: str,
    opp: str = typer.Option(None, "--opp", help="Opportunity whose RFP to include."),
    max_calls: int = typer.Option(None, "--max-calls", min=3, max=40, help="LLM call cap."),
) -> None:
    """Offline multi-step research over library/ (+ the active RFP); saves a cited report."""
    root, _store, sess = _session()
    try:
        cfg = cfgmod.load_config()
        opportunity = None
        if opp or sess.active_opp:
            opportunity = session.active_opportunity(root, sess, opp)
        report = researchmod.run_research(
            question,
            root,
            get_llm(),
            cfg,
            opp_dir=opportunity.path if opportunity else None,
            max_calls=max_calls,
            on_status=_status,
        )
    except (cfgmod.ConfigError, session.SessionError, researchmod.ResearchError, LLMError) as exc:
        _fail(str(exc))
    out_dir = opportunity.path / "research" if opportunity else root / "workspace" / "research"
    path = researchmod.save_report(report, out_dir)
    typer.echo(report.to_markdown())
    typer.echo(f"\nSaved: {path}")


# --- chat ------------------------------------------------------------------------------------


@app.command("chat")
def chat_cmd() -> None:
    """Chat REPL over the router (same behaviour as the Open WebUI model).

    `:attach <path>` attaches a file to your next message; `:quit` exits.
    """
    from studio.router import Router, RouterContext

    router = Router(RouterContext(cfgmod.project_root(), get_llm, allow_local_paths=True))
    sess = router.session(os.environ.get("STUDIO_SESSION", "cli-chat"))
    attachments: list[Path] = []
    typer.echo("Proposal Studio chat — `/help` for commands, `:quit` to exit.")

    async def run(message: str, files: list[Path]) -> None:
        async for chunk in router.handle(message, files, sess, emit=_emit_status):
            typer.echo(chunk, nl=False)
        typer.echo()

    while True:
        try:
            line = input("you> ")
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip() in (":quit", ":q", ":exit"):
            break
        if line.startswith(":attach "):
            path = Path(line.removeprefix(":attach ").strip()).expanduser()
            if not path.exists():
                typer.echo(f"No such file: {path}")
                continue
            attachments.append(path)
            typer.echo(f"Attached {path.name} (sent with your next message).")
            continue
        if not line.strip() and not attachments:
            continue
        asyncio.run(run(line, attachments))
        attachments = []


@app.command("ui")
def ui_cmd(
    port: int = typer.Option(8765, "--port", help="Port on 127.0.0.1."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't open a browser tab."),
) -> None:
    """Start the Proposal Studio chat app in your browser (local only)."""
    import webbrowser

    from studio.ui.server import make_server

    root = cfgmod.project_root()
    if not (root / "config").is_dir():
        _fail(f"No config/ folder in {root}. Run from the project folder or set STUDIO_HOME.")
    try:
        server = make_server(root, lambda: OllamaClient(cfgmod.load_config(root).models), port)
    except OSError as exc:
        _fail(f"Can't listen on port {port} ({exc}). Try `studio ui --port {port + 1}`.")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    typer.echo(f"Proposal Studio is running at {url}  (Ctrl+C to stop)")
    if not no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
    finally:
        server.server_close()


def _emit_status(event: dict) -> None:
    data = event.get("data", {})
    if not data.get("done"):
        _status(data.get("description", ""))


# --- agents --------------------------------------------------------------------------------


@app.command("agent")
def agent_cmd(
    name: str = typer.Argument(None, help="Agent name from config/agents.yaml; omit to list."),
    task: str = typer.Argument(None, help="What the agent should do."),
    yes: bool = typer.Option(False, "--yes", help="Apply and copy back without asking."),
    opp: str = typer.Option(None, "--opp", help="Opportunity id (default: active)."),
) -> None:
    """Run an agent CLI in the opportunity sandbox: plan → apply → copy back (with approvals)."""
    from studio.agents.adapters import SLOW_WARNING, agents_text, run_text
    from studio.agents.base import AgentError, AgentRunner

    cfg = cfgmod.load_config()
    if not name:
        typer.echo(agents_text(cfg.agents))
        return
    if not task:
        _fail('Usage: studio agent <name> "<task>"')
    try:
        root, opp_dir, _opp_id = _opp_dir(opp)
        runner = AgentRunner(
            cfg.agents, name, root, opp_dir, block_cloud=cfg.models.block_cloud_models
        )
        typer.echo(SLOW_WARNING.strip("_"))
        plan = runner.plan(task, on_line=lambda line: _status(line[:120]))
        typer.echo(run_text(plan))
        if not plan.ok or not (yes or typer.confirm("Apply this in the sandbox?")):
            raise typer.Exit(0 if plan.ok else 1)
        applied = runner.apply(task, on_line=lambda line: _status(line[:120]))
        typer.echo(run_text(applied))
        if not applied.changed or not (yes or typer.confirm("Copy the changes back?")):
            return
        copied = runner.copy_back()
        typer.echo(f"Copied back: {', '.join(copied) or 'nothing'}")
    except (session.SessionError, AgentError) as exc:
        _fail(str(exc))


# --- Open WebUI and smoke test ---------------------------------------------------------------


@owui_app.command("prompts")
def owui_prompts_cmd(
    out: Path = typer.Option(Path("owui/prompts"), "--out", help="Output folder."),
) -> None:
    """Regenerate owui/prompts/*.json (slash-command shortcuts) from config/routes.yaml."""
    from studio.owui import write_prompts

    root = cfgmod.project_root()
    paths = write_prompts(cfgmod.load_config().routes, out if out.is_absolute() else root / out)
    typer.echo(f"Wrote {len(paths)} files to {paths[0].parent}")


@owui_app.command("install")
def owui_install_cmd(
    token: str = typer.Option(..., "--token", envvar="OWUI_API_KEY", help="Admin API key (sk-…)."),
    url: str = typer.Option("http://localhost:8080", "--url", help="Local Open WebUI URL."),
    global_filter: bool = typer.Option(
        False, "--global-filter", help="Enable the PHI filter for all models."
    ),
) -> None:
    """Install/update the Proposal Studio functions and prompts into a local Open WebUI."""
    from studio.owui import InstallError, install

    try:
        install(url, token, cfgmod.project_root(), global_filter=global_filter, log=typer.echo)
    except (InstallError, cfgmod.ConfigError, httpx.HTTPError) as exc:
        _fail(str(exc))
    _next("open Open WebUI, pick the **Proposal Studio** model and type `/help`")


@app.command("smoke")
def smoke_cmd(
    keep: bool = typer.Option(False, "--keep", help="Keep the temporary project folder."),
) -> None:
    """End-to-end check on the real models: synthetic RFP → ingest → ask → digest → render."""
    from studio.smoke import run_smoke

    ok = run_smoke(cfgmod.project_root(), get_llm, keep=keep, log=typer.echo)
    if not ok:
        raise typer.Exit(1)


@app.command("docs")
def docs_cmd() -> None:
    """Regenerate docs/commands.md and owui/prompts/ from config/routes.yaml."""
    from studio.owui import write_prompts

    root = cfgmod.project_root()
    routes = cfgmod.load_config().routes
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "commands.md").write_text(views.commands_markdown(routes), encoding="utf-8")
    write_prompts(routes, root / "owui" / "prompts")
    typer.echo("Wrote docs/commands.md and owui/prompts/")


@app.command("bench")
def bench_cmd(
    cpu: bool = typer.Option(False, "--cpu", help="Force CPU-only inference (num_gpu=0)."),
) -> None:
    """Time each route against the performance budget on the real models (synthetic RFP)."""
    from studio.bench import run_bench

    timings = run_bench(cfgmod.project_root(), cpu_only=cpu, log=typer.echo)
    if any(t.ok is False for t in timings):
        raise typer.Exit(1)


# --- templates and render -------------------------------------------------------------------


@template_app.command("inspect")
def template_inspect(path: Path) -> None:
    """List a template's layouts and placeholders; write <name>.layouts.json beside it."""
    try:
        out, data = inspector.write_layouts_json(path)
    except inspector.TemplateError as exc:
        _fail(str(exc))
    typer.echo(inspector.layouts_table(data))
    typer.echo(f"\nWrote {out}")
    _next("map each slide_type to a layout and placeholder idx in config/layout_map.yaml")


@template_app.command("sample")
def template_sample(
    out: Path = typer.Option(
        Path("templates/sample/proposal-sample.pptx"), "--out", help="Where to write it."
    ),
) -> None:
    """(Re)generate the neutral sample template."""
    path = build_sample_template(out if out.is_absolute() else cfgmod.project_root() / out)
    typer.echo(f"Wrote {path}")


@app.command("render")
def render_cmd(
    opp: str = typer.Option(None, "--opp", help="Opportunity id (default: active)."),
    deck: Path = typer.Option(None, "--deck", help="deck.json to render (default: the opp's)."),
    template: Path = typer.Option(None, "--template", help="Template (default: layout_map)."),
    out: Path = typer.Option(None, "--out", help="Output folder (default: the opp's out/)."),
) -> None:
    """Render deck.json to a versioned PPTX on the template, with a QA report. No LLM."""
    root = cfgmod.project_root()
    try:
        cfg = cfgmod.load_config()
        if deck and out:
            deck_path, out_dir = deck, out
        else:
            _root, _store, sess = _session()
            opportunity = session.active_opportunity(root, sess, opp)
            deck_path = deck or opportunity.path / "deck.json"
            out_dir = out or opportunity.path / "out"
        if not deck_path.exists():
            _fail(f"No deck at {deck_path} yet. Build one with `/deck` first.")
        deck_model = Deck.model_validate_json(deck_path.read_text(encoding="utf-8"))
    except (cfgmod.ConfigError, session.SessionError) as exc:
        _fail(str(exc))
    except ValueError as exc:  # pydantic ValidationError
        _fail(f"{deck_path} isn't a valid deck: {exc}")
    template_path = template or Path(cfg.layout_map.template)
    if not template_path.is_absolute():
        template_path = root / template_path
    report = render_deck(deck_model, cfg.layout_map, template_path, out_dir, deck_model.opportunity)
    typer.echo(report.qa.to_markdown(report.path))
    if not report.qa.ok:
        raise typer.Exit(1)


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
    try:
        loaded = client.loaded_models()
    except LLMError:
        loaded = []
    if len(loaded) > 1:  # informational: RAM pressure on a 16 GB laptop
        checks.append(
            Check(
                True,
                f"Note: {len(loaded)} models loaded at once ({', '.join(loaded)}). On 16 GB, start "
                "Ollama via scripts/start.* so OLLAMA_MAX_LOADED_MODELS=1 applies",
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
