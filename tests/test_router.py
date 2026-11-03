import asyncio
import time
from pathlib import Path

import pytest

from studio import config as cfgmod
from studio.router import Command, Router, RouterContext, RouterError, parse
from tests.conftest import REPO_ROOT
from tests.fakes import FakeLLM
from tests.test_digest import GROUP_A

ROUTE = {"route": "digest", "alternative": "ask", "confidence": 0.9, "args": ""}
UNSURE = {"route": "ask", "alternative": "research", "confidence": 0.3, "args": ""}


@pytest.fixture
def home(studio_home: Path) -> Path:
    tpl = REPO_ROOT / "templates" / "sample" / "proposal-sample.pptx"
    (studio_home / "templates" / "sample").mkdir(parents=True)
    (studio_home / "templates" / "sample" / tpl.name).write_bytes(tpl.read_bytes())
    return studio_home


def make(home: Path, **canned) -> tuple[Router, FakeLLM]:
    llm = FakeLLM(
        {
            "RouteDecision": canned.get("route", ROUTE),
            "DigestPart": GROUP_A,
            "WriteUnderstandingContent": {"title": "U", "bullets": ["a", "b", "c"]},
            "WriteBeforeAfterContent": {
                "title": "B",
                "before": ["a", "b", "c"],
                "after": ["d", "e", "f"],
            },
        },
        text="Proposals are due March 15, 2027 [1].",
    )
    return Router(RouterContext(home, lambda: llm, allow_local_paths=True)), llm


def test_every_command_and_alias_parses(home: Path) -> None:
    routes = cfgmod.load_config(home).routes
    for name in routes.commands:
        assert parse(f"/{name} x", routes) == Command(name, "x")
    for alias, target in routes.aliases.items():
        assert parse(f"/{alias}", routes).name == target
    assert parse("hello", routes) is None
    with pytest.raises(RouterError, match="Did you mean `/deck`"):
        parse("/dek", routes)


def test_unknown_command_reply(home: Path) -> None:
    router, _ = make(home)
    assert "⚠ Unknown command `/dek`. Did you mean `/deck`?" in router.reply("/dek")


def test_full_pipeline_through_handle(home: Path, rfp_files) -> None:
    router, llm = make(home)
    sess = router.session("chat-1")
    events: list[dict] = []
    chunks: list[str] = []

    async def run(message: str, files=()):
        chunks.clear()
        async for chunk in router.handle(message, files, sess, emit=events.append):
            chunks.append(chunk)
        return "".join(chunks)

    out = asyncio.run(run("/new acme Acme Health Plan AI RFP"))
    assert out.startswith("→ routed to /new (command)") and "Next:" in out

    out = asyncio.run(run("", [rfp_files["pdf"]]))
    assert out.startswith("→ routed to /ingest (rules)") and "new: acme_rfp.pdf" in out
    assert any(e["data"]["description"].startswith("Embedding") for e in events)
    assert events[-1] == {"type": "status", "data": {"description": "Done", "done": True}}

    out = asyncio.run(run("When are proposals due?"))
    assert out.startswith("→ routed to /ask (rules)")
    assert "[2 Submission Instructions, p.1]" in out and len(chunks) > 3  # streamed

    out = asyncio.run(run("/digest xlsx"))
    assert "## RFP digest" in out and "requirements-v1.xlsx" in out
    out = asyncio.run(run("/outline"))
    assert "⬜ **governance**" in out and "Next: `/deck`" in out  # no compliance in this digest
    out = asyncio.run(run("/deck"))
    assert "Wrote 10 slide(s)" in out and "Please review:" in out
    out = asyncio.run(run("/render"))
    assert "## Render QA — 10 slides, ✅ no errors" in out
    assert sess.last_outputs["render"].endswith("acme-v1.pptx")

    again = router.session("chat-1")  # persisted
    assert again.active_opp == "acme" and again.last_outputs["render"]
    assert router.session("chat-2").active_opp is None  # per chat


def test_auto_routed_render_waits_for_approval(home: Path) -> None:
    router, llm = make(home)
    sess = router.session("c")
    out = router.reply("please render the pptx", session=sess)
    assert out.startswith("→ routed to /render (rules)") and "won't run it automatically" in out
    assert sess.last_outputs["pending"]["command"] == "render"
    out = router.reply("/reject", session=sess)
    assert "Cancelled `/render`" in out and "pending" not in sess.last_outputs
    router.reply("make a powerpoint", session=sess)
    out = router.reply("/yes", session=sess)  # alias of /approve
    assert "Running `/render`" in out and "No active opportunity" in out
    assert "Nothing is waiting" in router.reply("/approve", session=sess)
    assert not llm.calls  # rules never call the model


def test_explicit_render_runs_immediately(home: Path) -> None:
    router, _ = make(home)
    router.reply("/new acme")
    out = router.reply("/render")
    assert "No deck yet." in out and "won't run" not in out


def test_classifier_confident_and_unsure(home: Path) -> None:
    router, llm = make(home)
    router.reply("/new acme")
    out = router.reply("list what they need from us")
    assert out.startswith("→ routed to /digest (classifier, 0.90)")
    assert llm.calls[0]["schema"] == "RouteDecision" and llm.calls[0]["role"] == "router"
    router, _ = make(home, route=UNSURE)
    out = router.reply("hello there")
    assert "→ not routed" in out and "Did you mean `/ask` or `/research`?" in out
    router, _ = make(home, route="not json")
    assert "couldn't route that" in router.reply("hmm")


def test_classifier_never_auto_runs_harvest(home: Path) -> None:
    router, _ = make(
        home, route={"route": "harvest", "alternative": "blocks", "confidence": 0.95, "args": ""}
    )
    sess = router.session("h")
    out = router.reply("pull reusable content from old decks", session=sess)
    assert (
        "won't run it automatically" in out and sess.last_outputs["pending"]["command"] == "harvest"
    )


def test_phi_ingest_needs_approval(home: Path, tmp_path: Path) -> None:
    router, _ = make(home)
    sess = router.session("p")
    router.reply("/new acme", session=sess)
    leaky = tmp_path / "leaky.txt"
    leaky.write_text("Member SSN 123-45-6789\n")
    out = router.reply("", [leaky], session=sess)
    assert "Possible PHI found" in out and "`/approve` to ingest anyway" in out
    out = router.reply("/approve", session=sess)
    assert "new: leaky.txt" in out


def test_paths_refused_without_local_access(home: Path, rfp_files) -> None:
    llm = FakeLLM()
    router = Router(RouterContext(home, lambda: llm, allow_local_paths=False))
    router.reply("/new acme")
    out = router.reply(f"/ingest {rfp_files['pdf']}")
    assert "Attach the files to your message" in out


def test_config_agent_help_status(home: Path) -> None:
    router, _ = make(home)
    assert "worker: qwen3:8b" in router.reply("/config")
    assert "Set `worker.model`" in router.reply("/config set worker.model qwen3:4b")
    assert "⚠" in router.reply("/config set worker.model big:cloud") and "cloud" in router.reply(
        "/config set worker.model big:cloud"
    )
    assert "Overrides cleared" in router.reply("/config reset")
    assert "Phase 8" in router.reply("/agent opencode fix it")
    help_text = router.reply("/help")
    assert "`/research`" in help_text and "`/q`→`/ask`" in help_text
    assert "No active opportunity" in router.reply("/status")
    router.reply("/new acme")
    out = router.reply("/status")
    assert "Opportunity: acme" in out and "Next: `/ingest`" in out


def test_every_handler_ends_with_next(home: Path) -> None:
    router, _ = make(home)
    router.reply("/new acme")
    for message in (
        "/help",
        "/use",
        "/status",
        "/blocks",
        "/outline",
        "/library status",
        "/config",
    ):
        assert "Next:" in router.reply(message), message


def test_rules_routing_is_fast_and_offline(home: Path, rfp_files) -> None:
    router, llm = make(home)
    router.reply("/new acme")
    router.reply("", [rfp_files["pdf"]])
    sess = router.session("default")
    cfg = cfgmod.load_config(home)
    start = time.perf_counter()
    decision = router.decide("When are proposals due?", [], sess, cfg, lambda: llm)
    assert time.perf_counter() - start < 1.0
    assert decision.command == Command("ask", "When are proposals due?") and decision.how == "rules"
    assert not [c for c in llm.calls if c["schema"] == "RouteDecision"]


def test_auto_digest_shows_saved_digest(home: Path, rfp_files) -> None:
    router, llm = make(home)
    router.reply("/new acme")
    router.reply("", [rfp_files["pdf"]])
    router.reply("/digest")
    built = len([c for c in llm.calls if c["schema"] == "DigestPart"])
    out = router.reply("list what they need from us")  # classifier → digest
    assert "Showing the saved digest" in out
    assert len([c for c in llm.calls if c["schema"] == "DigestPart"]) == built  # no rebuild
