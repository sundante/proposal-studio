"""Chat router: parse ``/commands``, auto-route plain text, dispatch to the ``studio`` modules.

The router is code, not an agent. ``Router.handle()`` is the single entry point used by the
``studio chat`` REPL and (Phase 7) the Open WebUI pipe:

- ``/command args`` → that command (aliases from ``routes.yaml``).
- Plain text → rules first (attachments, keywords, "?" with an indexed RFP), then the router
  model's classifier; below ``auto_threshold`` it asks a one-line clarifying question.
- Routes in ``confirm_routes`` (render, agent, harvest) never auto-run: they wait for
  ``/approve``. Ingest PHI warnings use the same pending-confirmation mechanism.
- Every reply starts with ``→ routed to /x (how)`` and ends with a ``Next:`` hint.

Work runs in a worker thread so the (synchronous) LLM and file I/O never block the event loop;
chunks stream back as they are produced and status callbacks become ``emit`` events.
"""

from __future__ import annotations

import asyncio
import difflib
import inspect
import re
import shlex
from collections.abc import AsyncIterator, Callable, Generator, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, create_model

from studio import blocks as blockmod
from studio import config as cfgmod
from studio import digest as digestmod
from studio import ingest as ingestmod
from studio import research as researchmod
from studio import session as sessmod
from studio import views
from studio.agents.adapters import SLOW_WARNING, agents_text, run_text
from studio.agents.base import AgentError, AgentRunner
from studio.config import RoutesConfig, StudioConfig
from studio.deck import storyline, writer
from studio.deck.schemas import Deck
from studio.guards import GuardError
from studio.llm import LLMClient, LLMError, StructuredOutputError
from studio.rag import LIBRARY_COLLECTIONS, VectorIndex, answer
from studio.render.inspect_template import TemplateError
from studio.render.renderer import render

StatusFn = Callable[[str], None]
Emit = Callable[[dict[str, Any]], Any]

USER_ERRORS = (
    cfgmod.ConfigError,
    sessmod.SessionError,
    ingestmod.IngestError,
    digestmod.DigestError,
    blockmod.BlockError,
    storyline.OutlineError,
    writer.DeckError,
    researchmod.ResearchError,
    TemplateError,
    GuardError,
    LLMError,
    AgentError,
)
# Commands the classifier may pick (session/meta commands need an explicit /command).
CLASSIFIER_EXCLUDE = {"approve", "reject", "config", "new", "use", "toggle", "library", "edit"}
ARGS_FROM_TEXT = {"ask", "research", "blocks"}  # auto-routed text becomes the argument


class RouterError(ValueError):
    """A user-facing problem with the message itself (unknown command, bad arguments)."""


@dataclass(frozen=True)
class Command:
    """A parsed command."""

    name: str
    args: str = ""


FENCE = re.compile(r"^\s*(`{3,}|~{3,})[\w-]*[ \t]*\n?(.*?)\n?[ \t]*\1\s*$", re.S)


def unfence(text: str) -> str:
    """``text`` without a surrounding code fence or inline backticks (pasted commands)."""
    match = FENCE.match(text)
    if match:
        return match.group(2).strip()
    stripped = text.strip()
    inner = stripped[1:-1]
    if len(stripped) > 1 and stripped[0] == stripped[-1] == "`" and "`" not in inner:
        return inner.strip()
    return text


def parse(text: str, routes: RoutesConfig) -> Command | None:
    """``/name args`` → :class:`Command` (aliases resolved), or None for plain text.

    A command pasted inside a code fence or backticks (```/new x``` or `/new x`) still counts.
    Raises :class:`RouterError` for an unknown command, suggesting the closest one.
    """
    match = re.match(r"^\s*/([A-Za-z][\w-]*)\s*(.*)$", unfence(text), re.S)
    if not match:
        return None
    name = match.group(1).lower()
    name = routes.aliases.get(name, name)
    if name not in routes.commands:
        close = difflib.get_close_matches(name, list(routes.commands), n=1)
        hint = f" Did you mean `/{close[0]}`?" if close else " Type `/help` for the list."
        raise RouterError(f"Unknown command `/{match.group(1)}`.{hint}")
    return Command(name, match.group(2).strip())


@dataclass
class Decision:
    """How a message was routed."""

    command: Command | None
    how: str  # command | rules | classifier | pending
    confidence: float | None = None
    clarification: str = ""

    def route_line(self) -> str:
        if self.command is None:
            return "→ not routed (needs clarification)"
        detail = self.how if self.confidence is None else f"{self.how}, {self.confidence:.2f}"
        return f"→ routed to /{self.command.name} ({detail})"


@dataclass
class RouterContext:
    """What the router needs from its host."""

    root: Path
    llm_factory: Callable[[], LLMClient]
    allow_local_paths: bool = False  # REPL: True. Chat UI: files arrive as attachments.
    route_overrides: dict[str, Any] = field(default_factory=dict)  # e.g. Open WebUI Valves

    def config(self) -> StudioConfig:
        cfg = cfgmod.load_config(self.root)
        if self.route_overrides:
            cfg = cfg.model_copy(
                update={"routes": cfg.routes.model_copy(update=self.route_overrides)}
            )
        return cfg


@dataclass
class Call:
    """One handler invocation."""

    ctx: RouterContext
    cfg: StudioConfig
    session: sessmod.Session
    args: str
    attachments: list[Path]
    status: StatusFn
    confirmed: bool = False
    auto: bool = False  # routed from plain text rather than an explicit /command
    _llm: LLMClient | None = field(default=None, repr=False)

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = self.ctx.llm_factory()
        return self._llm

    def opportunity(self) -> sessmod.Opportunity:
        return sessmod.active_opportunity(self.ctx.root, self.session)

    def produced(self, path: Path) -> None:
        """Record a file this message created (the chat UI offers it for download)."""
        self.session.last_outputs.setdefault("produced", []).append(str(path))

    def pend(self, command: str, args: str = "", **extra: Any) -> None:
        self.session.last_outputs["pending"] = {
            "command": command,
            "args": args,
            "attachments": [str(p) for p in self.attachments],
            **extra,
        }


def _next(hint: str) -> str:
    return f"\n\nNext: {hint}"


# --- handlers -------------------------------------------------------------------------------


def h_help(c: Call) -> Iterator[str]:
    lines = ["## Commands"]
    lines += [f"- `/{name}` — {spec.help}" for name, spec in c.cfg.routes.commands.items()]
    aliases = ", ".join(f"`/{a}`→`/{t}`" for a, t in c.cfg.routes.aliases.items())
    lines += [
        "",
        f"Aliases: {aliases}",
        "",
        "Or just type: questions go to `/ask` when an RFP "
        "is ingested; other requests are routed automatically (with a status line).",
    ]
    yield "\n".join(lines) + _next("`/new <opp-id> [title]` to start")


def h_new(c: Call) -> Iterator[str]:
    parts = c.args.split(maxsplit=1)
    if not parts:
        raise RouterError("Usage: `/new <opp-id> [title]`, e.g. `/new acme-2026 Acme AI RFP`.")
    opp = sessmod.create_opportunity(c.ctx.root, parts[0], parts[1] if len(parts) > 1 else "")
    c.session.active_opp = opp.id
    yield f"Created **{opp.id}** (now active)." + _next("attach the RFP files and send `/ingest`")


def h_use(c: Call) -> Iterator[str]:
    if not c.args:
        opps = sessmod.list_opportunities(c.ctx.root)
        if not opps:
            yield "No opportunities yet." + _next("`/new <opp-id> [title]`")
            return
        lines = [
            f"{'**→**' if o.id == c.session.active_opp else '-'} {o.id} {o.title}".rstrip()
            for o in opps
        ]
        yield "\n".join(lines) + _next("`/use <opp-id>`")
        return
    if len(c.args.split()) > 1:
        raise RouterError(
            "`/use` expects an opportunity id, e.g. `/use acme-2026` (send `/use` alone to list "
            "them). To ask a question, just type it."
        )
    opp = sessmod.get_opportunity(c.ctx.root, c.args.split()[0])
    c.session.active_opp = opp.id
    yield f"Active opportunity: **{opp.id}**" + _next("`/status`")


def h_status(c: Call) -> Iterator[str]:
    info = sessmod.opportunity_status(c.opportunity())
    loaded = None
    try:
        loaded_fn = getattr(c.llm, "loaded_models", None)
        loaded = loaded_fn() if loaded_fn else None
    except LLMError:
        loaded = None
    yield views.status_text(info, loaded) + _next(views.status_next(info))


def _ingest_paths(c: Call) -> list[Path]:
    paths = list(c.attachments)
    if c.args:
        if not c.ctx.allow_local_paths:
            raise RouterError(
                "`/ingest` doesn't take instructions: attach the files and send `/ingest` on its "
                "own, then ask your question."
            )
        paths += [Path(p).expanduser() for p in shlex.split(c.args)]
    return paths


def h_ingest(c: Call) -> Iterator[str]:
    opp = c.opportunity()
    paths = _ingest_paths(c)
    report = ingestmod.ingest(
        opp.path,
        paths,
        c.llm,
        c.cfg.rag,
        c.cfg.models.roles["embed"].model,
        confirm_phi=c.confirmed,
        on_status=c.status,
    )
    if report.blocked:
        c.pend("ingest", c.args)
        yield views.phi_blocked_text(report) + _next(
            "check the files; `/approve` to ingest anyway, or `/reject`"
        )
        return
    yield views.ingest_report_text(report) + _next(
        'ask a question, e.g. "When are proposals due?", or `/digest`'
    )


def h_ask(c: Call) -> Iterator[str]:
    if not c.args:
        raise RouterError("Usage: `/ask <question>`.")
    opp = c.opportunity()
    index = VectorIndex(opp.path / "index")
    if not len(index):
        yield f"Nothing ingested for {opp.id} yet." + _next("attach the RFP and send `/ingest`")
        return
    yield from answer(c.args, index, c.llm, c.cfg.rag, on_status=c.status)
    yield _next("another question, or `/digest`")


def h_digest(c: Call) -> Iterator[str]:
    opp = c.opportunity()
    words = {w.lower().lstrip("-") for w in c.args.split()}
    warnings: list[str] = []
    current = (opp.path / digestmod.DIGEST_FILE).exists() and not digestmod.is_stale(opp.path)
    if c.auto and current:  # "summarise the requirements" shouldn't trigger a rebuild
        words.add("show")
        warnings.append("Showing the saved digest; send `/digest` to rebuild it.")
    if "show" in words:
        result = digestmod.load_digest(opp.path)
        if result is None:
            yield "No digest yet." + _next("`/digest`")
            return
        if digestmod.is_stale(opp.path):
            warnings.append("Files changed since this digest; send `/digest` to rebuild.")
    else:
        report = digestmod.build_digest(opp.path, c.llm, c.cfg.rag, on_status=c.status)
        result, warnings = report.digest, report.warnings
    text = digestmod.render_summary(result, warnings)
    if "xlsx" in words:
        path = digestmod.export_matrix(result, opp.path / "out", opp.id)
        c.produced(path)
        text += f"\n\nRequirements matrix: `{path}`"
    yield text


def h_harvest(c: Call) -> Iterator[str]:
    clients = [x.strip() for x in c.args.split(",") if x.strip()]
    report = blockmod.harvest(c.ctx.root, c.llm, c.cfg.deck, clients=clients, on_status=c.status)
    yield views.harvest_report_text(report) + _next(
        "review the YAML in `library/blocks/` (set `needs_review: false`), then `/blocks`"
    )


def h_blocks(c: Call) -> Iterator[str]:
    if c.args:
        hits = blockmod.search_blocks(
            c.ctx.root, c.args, c.llm, c.cfg.models.roles["embed"].model, k=10
        )
    else:
        hits = [(b, 0.0) for b in blockmod.load_blocks(c.ctx.root)]
    if not hits:
        yield "No blocks yet." + _next("`/harvest`")
        return
    yield views.blocks_text(hits, show_scores=bool(c.args)) + _next("`/outline` then `/deck`")


def h_outline(c: Call) -> Iterator[str]:
    opp = c.opportunity()
    digest = digestmod.load_digest(opp.path)
    if digest is None:
        yield "No digest yet." + _next("`/digest`")
        return
    outline = storyline.build_outline(
        c.cfg.storyline, digest, opp.id, storyline.load_outline(opp.path)
    )
    storyline.save_outline(opp.path, outline)
    yield storyline.render_outline(outline)


def h_toggle(c: Call) -> Iterator[str]:
    parts = c.args.split()
    if len(parts) != 2 or parts[1] not in ("on", "off"):
        raise RouterError("Usage: `/toggle <slide_id> on|off`.")
    opp = c.opportunity()
    outline = storyline.load_outline(opp.path)
    if outline is None:
        yield "No outline yet." + _next("`/outline`")
        return
    outline = storyline.toggle(outline, parts[0], parts[1] == "on")
    storyline.save_outline(opp.path, outline)
    yield storyline.render_outline(outline)


def h_deck(c: Call) -> Iterator[str]:
    opp = c.opportunity()
    report = writer.write_deck(
        opp.path,
        opp.id,
        c.ctx.root,
        c.llm,
        c.cfg,
        slide_id=c.args.split()[0] if c.args else None,
        on_status=c.status,
    )
    parts = [f"Wrote {len(report.written)} slide(s)."]
    parts += ["\n".join(writer.slide_text(s)) for s in report.deck.slides if s.id in report.written]
    flags = views.flags_text(report.flagged)
    yield "\n\n".join(parts + ([flags] if flags else [])) + _next(
        "`/render` (or `/edit <slide_id> <instruction>`)"
    )


def h_edit(c: Call) -> Iterator[str]:
    parts = c.args.split(maxsplit=1)
    if len(parts) != 2:
        raise RouterError("Usage: `/edit <slide_id> <instruction>`.")
    opp = c.opportunity()
    report = writer.edit_slide(
        opp.path, c.ctx.root, c.llm, c.cfg, parts[0], parts[1], on_status=c.status
    )
    flags = views.flags_text(report.flagged)
    yield (
        f"```diff\n{report.diff or '(no change)'}\n```"
        + (f"\n\n{flags}" if flags else "")
        + _next("`/render`")
    )


def h_render(c: Call) -> Iterator[str]:
    opp = c.opportunity()
    deck_path = opp.path / writer.DECK_FILE
    if not deck_path.exists():
        yield "No deck yet." + _next("`/deck`")
        return
    deck = Deck.model_validate_json(deck_path.read_text(encoding="utf-8"))
    template = Path(c.cfg.layout_map.template)
    template = template if template.is_absolute() else c.ctx.root / template
    c.status("Rendering…")
    report = render(deck, c.cfg.layout_map, template, opp.path / "out", deck.opportunity)
    c.session.last_outputs["render"] = str(report.path) if report.path else ""
    if report.path:
        c.produced(report.path)
    yield report.qa.to_markdown(report.path)


def h_research(c: Call) -> Iterator[str]:
    opp_dir = c.opportunity().path if c.session.active_opp else None
    report = researchmod.run_research(
        c.args, c.ctx.root, c.llm, c.cfg, opp_dir=opp_dir, on_status=c.status
    )
    out_dir = opp_dir / "research" if opp_dir else c.ctx.root / "workspace" / "research"
    path = researchmod.save_report(report, out_dir)
    c.produced(path)
    yield report.to_markdown() + f"\n\nSaved: `{path}`"


def h_library(c: Call) -> Iterator[str]:
    action = (c.args.split() or ["status"])[0]
    if action == "status":
        yield views.library_status_text(c.ctx.root) + _next("`/library index`")
        return
    if action != "index":
        raise RouterError("Usage: `/library index` or `/library status`.")
    out = []
    for name in LIBRARY_COLLECTIONS:
        report = ingestmod.index_library(
            c.ctx.root,
            name,
            c.llm,
            c.cfg.rag,
            c.cfg.models.roles["embed"].model,
            confirm_phi=c.confirmed,
            on_status=c.status,
        )
        if report.blocked:
            c.pend("library", "index")
            hits = views.phi_hits_text(report.phi_hits)
            out.append(f"{name}: possible PHI found; nothing indexed:\n{hits}")
            yield "\n".join(out) + _next("`/approve` to index anyway, or `/reject`")
            return
        out.append(views.library_report_text(name, report))
    yield "\n".join(out) + _next("`/research <question>`")


def h_agent(c: Call) -> Iterator[str]:
    """`/agent <name> <task>`: plan (throwaway copy) → approve → apply → approve → copy back."""
    parts = c.args.split(maxsplit=1)
    if not parts:
        yield agents_text(c.cfg.agents) + _next("`/agent <name> <task>`")
        return
    stage = "plan"
    if parts[0] in ("--apply", "--copy-back"):
        if not c.confirmed:
            raise RouterError("Start with `/agent <name> <task>`; later steps run via `/approve`.")
        stage, parts = parts[0][2:], parts[1].split(maxsplit=1) if len(parts) > 1 else []
    if len(parts) != 2:
        raise RouterError(
            "Usage: `/agent <name> <task>`, e.g. `/agent opencode tighten deck.json`."
        )
    name, task = parts
    opp = c.opportunity()
    runner = AgentRunner(
        c.cfg.agents, name, c.ctx.root, opp.path, block_cloud=c.cfg.models.block_cloud_models
    )

    def progress(line: str) -> None:
        c.status(f"{name}: {line[:90]}")

    if stage == "plan":
        yield SLOW_WARNING + "\n\n"
        c.status(f"{name}: planning in a throwaway copy…")
        run = runner.plan(task, on_line=progress)
        yield run_text(run)
        if run.ok:
            c.pend("agent", f"--apply {name} {task}")
            yield _next(f"`/approve` to let {name} make the changes in its sandbox, or `/reject`")
        else:
            yield _next("check the log, or try a clearer task")
    elif stage == "apply":
        c.status(f"{name}: applying in the sandbox…")
        run = runner.apply(task, on_line=progress)
        yield run_text(run)
        if run.ok and run.changed:
            c.pend("agent", f"--copy-back {name} {task}")
            yield _next("`/approve` to copy the changes into the opportunity, or `/reject`")
        else:
            yield _next("`/agent` again with a different task")
    else:
        copied = runner.copy_back()
        listed = ", ".join(f"`{p}`" for p in copied) or "nothing (no changes)"
        yield f"Copied back: {listed}. Previous versions are in `history/`." + _next(
            "`/render` to see the result"
        )


def h_config(c: Call) -> Iterator[str]:
    parts = c.args.split(maxsplit=2)
    if not parts:
        data = c.cfg.model_dump(mode="json")
        roles = {k: v["model"] for k, v in data["models"]["roles"].items()}
        summary = {
            "models": roles,
            "auto_route": data["routes"]["auto_route"],
            "auto_threshold": data["routes"]["auto_threshold"],
            "active_opportunity": c.session.active_opp,
            "agents": list(data["agents"]["agents"]),
        }
        yield f"```yaml\n{yaml.safe_dump(summary, sort_keys=False)}```" + _next(
            "`/config set <key> <value>` (e.g. `worker.model qwen3:4b`) or `/config reset`"
        )
    elif parts[0] == "set" and len(parts) == 3:
        cfgmod.set_value(parts[1], parts[2], c.ctx.root)
        yield f"Set `{parts[1]}` = `{parts[2]}` (saved to config/overrides.yaml)." + _next(
            "`/config`"
        )
    elif parts[0] == "reset":
        cfgmod.reset(c.ctx.root)
        yield "Overrides cleared; using the base config." + _next("`/config`")
    else:
        raise RouterError("Usage: `/config`, `/config set <key> <value>` or `/config reset`.")


HANDLERS: dict[str, Callable[[Call], Iterator[str]]] = {
    "help": h_help,
    "new": h_new,
    "use": h_use,
    "status": h_status,
    "ingest": h_ingest,
    "ask": h_ask,
    "digest": h_digest,
    "harvest": h_harvest,
    "blocks": h_blocks,
    "outline": h_outline,
    "toggle": h_toggle,
    "deck": h_deck,
    "edit": h_edit,
    "render": h_render,
    "research": h_research,
    "library": h_library,
    "agent": h_agent,
    "config": h_config,
}


# --- classifier -----------------------------------------------------------------------------


def classifier_schema(routes: RoutesConfig) -> type[BaseModel]:
    """``RouteDecision`` with ``route``/``alternative`` limited to routable commands."""
    names = tuple(n for n in routes.commands if n not in CLASSIFIER_EXCLUDE)
    choice = Literal.__getitem__(names)  # type: ignore[attr-defined]
    return create_model(
        "RouteDecision",
        route=(choice, ...),
        alternative=(choice, ...),
        confidence=(float, Field(ge=0.0, le=1.0)),
        args=(str, ""),
    )


def classifier_messages(text: str, routes: RoutesConfig) -> list[dict[str, str]]:
    """A short (~600 token) routing prompt with few-shot examples."""
    commands = "\n".join(
        f"/{n} — {s.help}" for n, s in routes.commands.items() if n not in CLASSIFIER_EXCLUDE
    )
    examples = "\n".join(f'"{e.text}" → {e.route}' for e in routes.examples)
    system = (
        "You route one message in a proposal workbench to the best command.\n"
        f"Commands:\n{commands}\n\nExamples:\n{examples}\n\n"
        "Return route, alternative (second most likely), confidence from 0 to 1 (low if the "
        "message is chit-chat or unclear), and args (the text to pass on, e.g. the question)."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


# --- router ---------------------------------------------------------------------------------


class Router:
    """Routes chat messages to handlers. One instance per host process."""

    def __init__(self, ctx: RouterContext) -> None:
        self.ctx = ctx
        self.store = sessmod.SessionStore(ctx.root)

    def session(self, key: str) -> sessmod.Session:
        """Load (or create) the session for a chat id."""
        return self.store.load(key)

    # -- routing --

    def decide(
        self,
        text: str,
        attachments: Sequence[Path],
        sess: sessmod.Session,
        cfg: StudioConfig,
        llm: Callable[[], LLMClient],
    ) -> Decision:
        """Pick the command for a message (rules before the classifier)."""
        routes = cfg.routes
        command = parse(text, routes)
        if command is not None:
            return Decision(command, "command")
        stripped = text.strip()
        if attachments and not stripped:
            return Decision(Command("ingest"), "rules")
        lowered = stripped.lower()
        for route, keywords in routes.keywords.items():
            if any(k.lower() in lowered for k in keywords):
                return Decision(
                    Command(route, stripped if route in ARGS_FROM_TEXT else ""), "rules"
                )
        if stripped.endswith("?") and sess.active_opp:
            try:
                opp = sessmod.get_opportunity(self.ctx.root, sess.active_opp)
                if len(VectorIndex(opp.path / "index")):
                    return Decision(Command("ask", stripped), "rules")
            except sessmod.SessionError:
                pass
        if not routes.auto_route or not stripped:
            return Decision(None, "rules", clarification="Type a command (see `/help`).")
        try:
            result = llm().generate_structured(
                "router", classifier_messages(stripped, routes), classifier_schema(routes)
            )
        except (StructuredOutputError, LLMError):
            return Decision(
                None,
                "classifier",
                clarification="I couldn't route that. Type `/help` for commands.",
            )
        if result.confidence < routes.auto_threshold:
            options = list(dict.fromkeys([result.route, result.alternative]))
            listed = " or ".join(f"`/{o}`" for o in options)
            return Decision(
                None,
                "classifier",
                result.confidence,
                clarification=f"Did you mean {listed}? Reply with the command.",
            )
        args = result.args.strip() or (stripped if result.route in ARGS_FROM_TEXT else "")
        return Decision(Command(result.route, args), "classifier", result.confidence)

    # -- processing (runs in a worker thread) --

    def process(
        self, text: str, attachments: Sequence[Path], sess: sessmod.Session, status: StatusFn
    ) -> Iterator[str]:
        """Route and run one message, yielding reply chunks.

        Files sent together with text are ingested first; the text is then routed as usual
        (so "here's the RFP — when is it due?" ingests, then answers).
        """
        try:
            cfg = self.ctx.config()
        except cfgmod.ConfigError as exc:
            yield f"⚠ {exc}"
            return
        llm_holder: list[LLMClient] = []

        def llm() -> LLMClient:
            if not llm_holder:
                llm_holder.append(self.ctx.llm_factory())
            return llm_holder[0]

        files = list(attachments)
        follow = self._follow_up_text(text, files, cfg.routes)
        if follow is not None:
            ok = yield from self._run(
                Decision(Command("ingest"), "rules"), files, sess, cfg, llm_holder, llm, status
            )
            if not ok or "pending" in sess.last_outputs:
                return
            yield "\n\n---\n\n"
            text, files = follow, []

        try:
            decision = self.decide(text, files, sess, cfg, llm)
        except RouterError as exc:
            yield f"⚠ {exc}"
            return
        yield from self._run(decision, files, sess, cfg, llm_holder, llm, status)

    def _follow_up_text(self, text: str, files: Sequence[Path], routes: RoutesConfig) -> str | None:
        """With attachments: the text to route after ingesting them (None: no two-step)."""
        if not files:
            return None
        try:
            parsed = parse(text, routes)
        except RouterError:
            return None
        if parsed is None:
            return text.strip() or None
        if parsed.name == "ingest" and parsed.args and not self.ctx.allow_local_paths:
            return parsed.args  # "/ingest understand the RFP" + file: ingest, then route the words
        return None

    def _run(
        self,
        decision: Decision,
        attachments: Sequence[Path],
        sess: sessmod.Session,
        cfg: StudioConfig,
        llm_holder: list[LLMClient],
        llm: Callable[[], LLMClient],
        status: StatusFn,
    ) -> Generator[str, None, bool]:
        """Run a routing decision; return False if it ended in an error or clarification."""
        yield decision.route_line() + "\n\n"
        if decision.command is None:
            yield decision.clarification
            return False

        command, confirmed = decision.command, False
        files = list(attachments)
        if command.name in ("approve", "reject"):
            pending = sess.last_outputs.pop("pending", None)
            if not pending:
                yield "Nothing is waiting for confirmation." + _next("`/status`")
                return False
            if command.name == "reject":
                yield f"Cancelled `/{pending['command']}`." + _next("`/status`")
                return True
            command = Command(pending["command"], pending.get("args", ""))
            files = [Path(p) for p in pending.get("attachments", [])]
            confirmed = True
            yield f"Running `/{command.name}`…\n\n"
        elif decision.how != "command" and command.name in cfg.routes.confirm_routes:
            sess.last_outputs["pending"] = {
                "command": command.name,
                "args": command.args,
                "attachments": [str(p) for p in files],
            }
            yield f"`/{command.name}` writes files, so I won't run it automatically." + _next(
                f"`/approve` to run `/{command.name}`, or `/reject`"
            )
            return True

        handler = HANDLERS.get(command.name)
        if handler is None:
            yield f"`/{command.name}` isn't available yet." + _next("`/help`")
            return False
        call = Call(self.ctx, cfg, sess, command.args, files, status, confirmed)
        call.auto = decision.how in ("rules", "classifier")
        call._llm = llm_holder[0] if llm_holder else None
        try:
            yield from handler(call)
        except (RouterError, *USER_ERRORS) as exc:
            yield f"⚠ {exc}"
            return False
        finally:
            if call._llm is not None and not llm_holder:
                llm_holder.append(call._llm)
        return True

    # -- async entry point --

    async def handle(
        self,
        message: str,
        attachments: Sequence[Path] = (),
        session: sessmod.Session | None = None,
        emit: Emit | None = None,
    ) -> AsyncIterator[str]:
        """Handle one chat message: stream reply chunks; send status events via ``emit``."""
        sess = session or self.session("default")
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        def put(kind: str, value: Any) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, value))

        def work() -> None:
            try:
                for chunk in self.process(message, attachments, sess, lambda s: put("status", s)):
                    put("chunk", chunk)
            except BaseException as exc:  # surfaced in the caller's task
                put("error", exc)
            finally:
                put("done", None)

        async def send(description: str, done: bool) -> None:
            if emit is None:
                return
            result = emit({"type": "status", "data": {"description": description, "done": done}})
            if inspect.isawaitable(result):
                await result

        worker = loop.run_in_executor(None, work)
        try:
            while True:
                kind, value = await queue.get()
                if kind == "chunk":
                    yield value
                elif kind == "status":
                    await send(value, False)
                elif kind == "error":
                    raise value
                else:
                    break
        finally:
            await worker
            self.store.save(sess)
            await send("Done", True)

    def reply(
        self, message: str, attachments: Sequence[Path] = (), session: sessmod.Session | None = None
    ) -> str:
        """Synchronous convenience: the whole reply as one string (tests, scripts)."""

        async def collect() -> str:
            return "".join([c async for c in self.handle(message, attachments, session)])

        return asyncio.run(collect())
