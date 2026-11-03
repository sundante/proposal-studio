import asyncio
import json
from pathlib import Path

import httpx
import pytest

from studio import config as cfgmod
from studio import owui
from studio.owui import (
    InstallError,
    PipeBridge,
    extract_user_text,
    install,
    materialize_files,
    phi_warning,
    prompt_entries,
    session_key,
    write_prompts,
)
from tests.conftest import REPO_ROOT
from tests.fakes import FakeLLM
from tests.test_digest import GROUP_A

RAG_PREFIX = (
    "### Task:\nRespond using the context.\n<context>\n<source id=1>stuff</source>\n</context>\n"
)


def body(text, *, as_parts: bool = False) -> dict:
    content = [{"type": "text", "text": text}] if as_parts else text
    return {
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": content}]
    }


def test_extract_user_text_strips_rag_context() -> None:
    assert extract_user_text(body("/ask When?")) == "/ask When?"
    assert extract_user_text(body("/deck", as_parts=True)) == "/deck"
    assert extract_user_text(body(RAG_PREFIX + "/ask When are proposals due?")) == (
        "/ask When are proposals due?"
    )
    assert extract_user_text({"messages": []}) == ""


def test_session_key_and_phi_warning() -> None:
    assert session_key("c1", {"id": "u"}) == "owui-chat-c1"
    assert session_key(None, {"id": "u"}) == "owui-user-u"
    assert "ssn" in phi_warning(body("Member SSN 123-45-6789"))
    assert phi_warning(body("When are proposals due?")) is None


def test_materialize_files(tmp_path: Path, rfp_files) -> None:
    stored = tmp_path / "uploads" / "1234_acme_rfp.pdf"
    stored.parent.mkdir()
    stored.write_bytes(rfp_files["pdf"].read_bytes())

    async def resolver(file_id: str):
        return str(stored) if file_id == "f1" else None

    items = [
        {"type": "file", "id": "f1", "file": {"filename": "acme_rfp.pdf"}},  # resolved by id
        {
            "type": "file",
            "file": {"id": "f2", "filename": "x.docx", "path": str(rfp_files["docx"])},
        },
        {"type": "file", "id": "missing", "file": {"filename": "gone.pdf"}},
        {"type": "collection", "id": "kb"},
    ]
    dest = tmp_path / "dest"
    dest.mkdir()
    paths, notes = asyncio.run(materialize_files(items, dest, resolver))
    assert [p.name for p in paths] == ["acme_rfp.pdf", "x.docx"]
    assert any("gone.pdf" in n for n in notes) and any("collection" in n for n in notes)


@pytest.fixture
def home(studio_home: Path) -> Path:
    tpl = REPO_ROOT / "templates" / "sample" / "proposal-sample.pptx"
    (studio_home / "templates" / "sample").mkdir(parents=True)
    (studio_home / "templates" / "sample" / tpl.name).write_bytes(tpl.read_bytes())
    return studio_home


def fake_llm(route=None) -> FakeLLM:
    return FakeLLM(
        {
            "RouteDecision": route
            or {"route": "digest", "alternative": "ask", "confidence": 0.9, "args": ""},
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


def bridge(home: Path, llm: FakeLLM, published: list) -> PipeBridge:
    async def publisher(path: Path, user_id: str):
        published.append((path.name, user_id))
        return f"/api/v1/files/{len(published)}/content"

    async def resolver(file_id: str):
        return None

    return PipeBridge(home, llm_factory=lambda: llm, resolver=resolver, publisher=publisher)


def collect(b: PipeBridge, text: str, **kw) -> str:
    async def run():
        return "".join(
            [c async for c in b.run(body(text), user={"id": "u1"}, chat_id="chat", **kw)]
        )

    return asyncio.run(run())


def test_bridge_pipeline_with_downloads(home: Path, rfp_files) -> None:
    published: list = []
    b = bridge(home, fake_llm(), published)
    assert "Created **acme**" in collect(b, "/new acme")
    item = {
        "type": "file",
        "id": "f",
        "file": {"filename": "acme_rfp.pdf", "path": str(rfp_files["pdf"])},
    }
    out = collect(b, "", files=[item])
    assert "→ routed to /ingest (rules)" in out and "new: acme_rfp.pdf" in out
    assert "[2 Submission Instructions, p.1]" in collect(b, "When are proposals due?")
    out = collect(b, "/digest xlsx")
    assert "📎 [Download acme-requirements-v1.xlsx](/api/v1/files/1/content)" in out
    collect(b, "/deck")
    out = collect(b, "/render")
    assert "no errors" in out and "📎 [Download acme-v1.pptx]" in out
    assert published[-1] == ("acme-v1.pptx", "u1")


def test_bridge_confirmation_dialog(home: Path) -> None:
    calls: list[dict] = []

    async def approve(event):
        calls.append(event)
        return True

    async def decline(event):
        return False

    b = bridge(home, fake_llm(), [])
    collect(b, "/new acme")
    out = collect(b, "make the powerpoint", event_call=decline)
    assert "won't run it automatically" in out and "Cancelled `/render`" in out
    out = collect(b, "make the powerpoint", event_call=approve)
    assert "Running `/render`" in out and "No deck yet." in out
    assert calls[0]["type"] == "confirmation" and "/render" in calls[0]["data"]["message"]


def test_bridge_tasks_and_missing_home(home: Path, tmp_path: Path) -> None:
    b = bridge(home, fake_llm(), [])
    assert collect(b, "make a title", task="title_generation") == ""
    lost = bridge(tmp_path / "nowhere", fake_llm(), [])
    assert "STUDIO_HOME" in collect(lost, "/help")


def test_default_opportunity_and_overrides(home: Path) -> None:
    b = bridge(home, fake_llm(), [])
    collect(b, "/new beta")
    b2 = PipeBridge(home, llm_factory=fake_llm, route_overrides={"auto_route": False})
    out = "".join(
        asyncio.run(
            _gather(
                b2.run(body("/status"), user={"id": "u"}, chat_id="new", default_opportunity="beta")
            )
        )
    )
    assert "Opportunity: beta" in out
    out = "".join(asyncio.run(_gather(b2.run(body("hello"), user={"id": "u"}, chat_id="new"))))
    assert "Type a command" in out  # auto-route off via Valves


async def _gather(agen):
    return [c async for c in agen]


def load_function(name: str):
    """Load an owui/*.py file the way Open WebUI does (exec into a fresh module dict)."""
    namespace: dict = {}
    exec((REPO_ROOT / "owui" / name).read_text(), namespace)
    return namespace


def test_function_files_load_like_open_webui(home: Path, monkeypatch) -> None:
    for name in ("router_pipe.py", "phi_filter.py"):
        text = (REPO_ROOT / "owui" / name).read_text()
        assert "requirements:" not in text  # Open WebUI would pip-install them
        assert text.startswith('"""\ntitle:')
    pipe_cls = load_function("router_pipe.py")["Pipe"]
    pipe = pipe_cls()
    pipe.valves = pipe.Valves(STUDIO_HOME=str(home))
    monkeypatch.setattr(owui, "OllamaClient", lambda *_a, **_k: fake_llm())
    out = "".join(
        asyncio.run(_gather(pipe.pipe(body("/help"), __user__={"id": "u"}, __chat_id__="c")))
    )
    assert "## Commands" in out

    filt = load_function("phi_filter.py")["Filter"]()
    events: list = []

    async def emit(e):
        events.append(e)

    msg = body("Patient SSN 123-45-6789")
    assert asyncio.run(filt.inlet(msg, __event_emitter__=emit)) == msg
    assert "Possible PHI" in events[0]["data"]["description"]
    filt.valves = filt.Valves(BLOCK=True)
    with pytest.raises(Exception, match="not sent"):
        asyncio.run(filt.inlet(msg))


def test_committed_prompts_match_routes(tmp_path: Path) -> None:
    routes = cfgmod.load_config(REPO_ROOT).routes
    write_prompts(routes, tmp_path)
    committed = REPO_ROOT / "owui" / "prompts"
    for path in tmp_path.iterdir():
        assert (committed / path.name).read_text() == path.read_text(), "run `studio owui prompts`"
    entries = json.loads((committed / "all.json").read_text())
    assert {
        "command": "deck",
        "name": entries[[e["command"] for e in entries].index("deck")]["name"],
        "content": "/deck ",
    } in entries
    assert all(not e["command"].startswith("/") for e in prompt_entries(routes))


def _api(existing: bool, seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer sk-test"
        if request.method == "GET":
            if existing:
                return httpx.Response(200, json={"id": "x", "is_active": True, "is_global": False})
            return httpx.Response(404, json={"detail": "not found"})
        if request.url.path.endswith("/prompts/create") and existing:
            return httpx.Response(
                400,
                json={"detail": "Uh-oh! This command is already registered. Command taken"},
            )
        return httpx.Response(200, json={"id": "x", "is_active": False, "is_global": False})

    return httpx.MockTransport(handler)


def test_install_creates_then_updates() -> None:
    seen: list = []
    log: list[str] = []
    install(
        "http://localhost:8080",
        "sk-test",
        REPO_ROOT,
        transport=_api(False, seen),
        log=log.append,
        global_filter=True,
    )
    paths = [p for _, p in seen]
    assert "/api/v1/functions/create" in paths
    assert "/api/v1/functions/id/proposal_studio/toggle" in paths
    assert "/api/v1/functions/id/proposal_studio_phi/toggle/global" in paths
    assert paths.count("/api/v1/prompts/create") == len(
        prompt_entries(cfgmod.load_config(REPO_ROOT).routes)
    )

    seen.clear()
    install(
        "http://127.0.0.1:8080", "sk-test", REPO_ROOT, transport=_api(True, seen), log=log.append
    )
    paths = [p for _, p in seen]
    assert (
        "/api/v1/functions/id/proposal_studio/update" in paths
        and "/api/v1/functions/create" not in paths
    )
    assert not any(p.endswith("/toggle") for p in paths)  # already active
    assert any("already exists (kept)" in line for line in log)


def test_install_refuses_remote_and_reports_auth() -> None:
    with pytest.raises(InstallError, match="only a local"):
        install("https://example.com", "sk", REPO_ROOT)
    denied = httpx.MockTransport(lambda r: httpx.Response(401, json={}))
    with pytest.raises(InstallError, match="admin API key"):
        install(
            "http://localhost:8080", "sk-test", REPO_ROOT, transport=denied, log=lambda _m: None
        )


def test_offline_env_and_scripts() -> None:
    env = (REPO_ROOT / "scripts" / "offline.env").read_text()
    for name in (
        "OFFLINE_MODE=true",
        "HF_HUB_OFFLINE=1",
        "ENABLE_WEB_SEARCH=False",
        "ENABLE_COMMUNITY_SHARING=False",
        "ENABLE_IMAGE_GENERATION=False",
        "RAG_EMBEDDING_ENGINE=ollama",
        "RAG_SYSTEM_CONTEXT=True",
        "ENABLE_TITLE_GENERATION=False",
        "OLLAMA_MAX_LOADED_MODELS=1",
        "OLLAMA_NO_CLOUD=1",
        "ENABLE_PERSISTENT_CONFIG=False",
        "ENABLE_OPENAI_API=False",
    ):
        assert name in env, name
    for script in ("start.ps1", "start.sh"):
        text = (REPO_ROOT / "scripts" / script).read_text()
        assert "offline.env" in text and "127.0.0.1" in text and "STUDIO_HOME" in text
    for script in ("setup.ps1", "setup.sh"):
        assert "open-webui==" in (REPO_ROOT / "scripts" / script).read_text()


def test_smoke_runs_with_fake_models() -> None:
    from studio.smoke import run_smoke

    lines: list[str] = []
    assert run_smoke(REPO_ROOT, fake_llm, log=lines.append), "\n".join(lines)
    assert lines[-1] == "Smoke test passed." and sum(line.startswith("PASS") for line in lines) == 7


def test_confirmation_error_never_approves(home: Path) -> None:
    async def disconnected(event):
        return {"error": "Client session disconnected."}

    b = bridge(home, fake_llm(), [])
    collect(b, "/new acme")
    out = collect(b, "make the powerpoint", event_call=disconnected)
    assert "Running `/render`" not in out and "type `/approve`" in out
    sess = b.router.session(session_key("chat", {"id": "u1"}))
    assert sess.last_outputs["pending"]["command"] == "render"  # still waiting


def test_agents_manifold_lists_enabled_agents(home: Path) -> None:
    from studio.owui import agent_from_model, agent_models

    models = agent_models(home)
    assert {"id": "opencode", "name": "Agent · OpenCode (local)"} in models
    assert all(m["id"] != "hermes" for m in models)  # disabled by default
    assert agent_from_model("proposal_studio_agents.opencode") == "opencode"
    pipe = load_function("agents_pipe.py")["Pipe"]()
    pipe.valves = pipe.Valves(STUDIO_HOME=str(home))
    assert pipe.pipes() == models
    assert not (REPO_ROOT / "owui" / "agents_pipe.py").read_text().count("requirements:")


def test_bridge_agent_prefix(home: Path) -> None:
    b = bridge(home, fake_llm(), [])
    collect(b, "/new acme")

    async def run(text):
        return "".join(
            [c async for c in b.run(body(text), user={"id": "u1"}, chat_id="chat", agent="hermes")]
        )

    assert "→ routed to /agent (command)" in asyncio.run(run("tighten the deck"))
    assert "Nothing is waiting" in asyncio.run(run("/approve"))  # commands pass through
