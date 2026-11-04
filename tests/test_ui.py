"""Studio UI server: real HTTP on a free port, FakeLLM, synthetic Acme fixtures."""

import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from studio import trust
from studio.ui.server import make_server
from studio.ui.store import title_from
from tests.test_router import make


def serve(home: Path, llm, **kwargs) -> tuple[ThreadingHTTPServer, str]:
    server = make_server(home, lambda: llm, port=0, **kwargs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def home(studio_home: Path) -> Path:
    from tests.test_router import home as router_home

    return router_home.__wrapped__(studio_home)


@pytest.fixture
def ws(home: Path) -> Path:
    """A trusted workspace folder (data lives here; config stays in ``home``)."""
    return trust.trust(home.parent / f"{home.name}-ws")


@pytest.fixture
def client(home: Path, ws: Path) -> Iterator[httpx.Client]:
    _, llm = make(home)
    server, base = serve(home, llm, workspace=ws)
    with httpx.Client(base_url=base, timeout=30) as c:
        yield c
    server.shutdown()
    server.server_close()


def events(resp: httpx.Response) -> list[tuple[str, dict]]:
    out = []
    for block in resp.text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def reply_text(evts: list[tuple[str, dict]]) -> str:
    return "".join(d["text"] for e, d in evts if e == "chunk")


def new_project(client: httpx.Client, name: str = "Acme Health Plan RFP") -> tuple[str, str]:
    resp = client.post("/api/projects", json={"name": name})
    assert resp.status_code == 201
    data = resp.json()
    return data["project"]["id"], data["chat"]["id"]


def test_serves_the_app(client: httpx.Client) -> None:
    page = client.get("/")
    assert page.status_code == 200 and "<title>Proposal Studio</title>" in page.text
    assert client.get("/app.js").headers["content-type"].startswith("text/javascript") or (
        "javascript" in client.get("/app.js").headers["content-type"]
    )
    assert client.get("/nope.js").status_code == 404
    health = client.get("/api/health").json()
    assert health["ollama"] is None and health["version"]


def test_drop_ask_analyse_build_download(client: httpx.Client, ws: Path, rfp_files) -> None:
    project, chat = new_project(client)
    assert project == "acme-health-plan-rfp"
    assert client.get("/api/projects").json()[0]["title"] == "Acme Health Plan RFP"

    pdf = rfp_files["pdf"]
    up = client.put(f"/api/projects/{project}/uploads/{pdf.name}", content=pdf.read_bytes())
    assert up.status_code == 201

    resp = client.post(
        f"/api/chats/{chat}/messages",
        json={"text": "When are proposals due?", "files": [pdf.name]},
    )
    evts = events(resp)
    text = reply_text(evts)
    assert "new: acme_rfp.pdf" in text and "→ routed to /ask (rules)" in text
    assert any(e == "status" for e, _ in evts) and evts[-1][0] == "done"
    assert [d["title"] for e, d in evts if e == "chat"] == ["When are proposals due?"]

    detail = client.get(f"/api/projects/{project}").json()
    assert [f["name"] for f in detail["files"]] == ["acme_rfp.pdf"]
    assert detail["status"]["chunks"] > 0
    assert not list((ws / "projects" / project / ".uploads").glob("*"))  # cleaned up
    assert (ws / "projects" / project / "input" / "acme_rfp.pdf").exists()

    saved = client.get(f"/api/chats/{chat}").json()
    assert saved["title"] == "When are proposals due?"
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]
    assert saved["messages"][0]["files"] == ["acme_rfp.pdf"]

    assert client.get(f"/api/projects/{project}/digest").status_code == 404
    resp = client.post(
        f"/api/chats/{chat}/messages",
        json={
            "text": "/deck",
            "display": "Build the slides",
            "steps": ["/digest", "/deck", "/render"],
        },
    )
    evts = events(resp)
    text = reply_text(evts)
    assert "## RFP digest" in text and "Wrote 10 slide(s)" in text and "Render QA" in text
    outputs = evts[-1][1]["outputs"]
    assert outputs == [f"{project}-v1.pptx"]

    pptx = client.get(f"/api/projects/{project}/out/{outputs[0]}")
    assert pptx.status_code == 200 and pptx.content[:2] == b"PK"
    assert "attachment" in pptx.headers["content-disposition"]
    assert client.get(f"/api/projects/{project}/digest").json()["digest"]["requirements"]
    assert len(client.get(f"/api/projects/{project}/deck").json()["slides"]) == 10
    saved = client.get(f"/api/chats/{chat}").json()
    assert saved["messages"][-1]["outputs"] == outputs
    assert saved["messages"][-2]["content"] == "Build the slides"

    after = client.delete(f"/api/projects/{project}/files/acme_rfp.pdf").json()
    assert after["files"] == [] and after["status"]["chunks"] == 0


def test_steps_stop_at_the_first_error(client: httpx.Client) -> None:
    _, chat = new_project(client, "Empty")
    evts = events(
        client.post(
            f"/api/chats/{chat}/messages", json={"steps": ["/deck", "/render"], "text": "x"}
        )
    )
    text = reply_text(evts)
    assert "⚠" in text and "/render" not in text.split("⚠", 1)[1]


def test_project_names_dedupe_and_rename(client: httpx.Client) -> None:
    first, _ = new_project(client, "Acme RFP")
    second, _ = new_project(client, "Acme RFP")
    assert (first, second) == ("acme-rfp", "acme-rfp-2")
    renamed = client.patch(f"/api/projects/{second}", json={"title": "Acme renewal"}).json()
    assert renamed["title"] == "Acme renewal"
    chat = client.post(f"/api/projects/{first}/chats").json()
    assert client.patch(f"/api/chats/{chat['id']}", json={"title": "Pricing"}).json()["title"] == (
        "Pricing"
    )
    assert client.delete(f"/api/chats/{chat['id']}").status_code == 200
    assert client.get(f"/api/chats/{chat['id']}").status_code == 400


def test_local_only_and_path_safety(client: httpx.Client) -> None:
    project, chat = new_project(client)
    assert client.get("/api/projects", headers={"Host": "evil.example"}).status_code == 403
    cross = client.post(
        "/api/projects", json={"name": "x"}, headers={"Origin": "http://evil.example"}
    )
    assert cross.status_code == 403
    assert client.put(f"/api/projects/{project}/uploads/.env", content=b"x").status_code == 400
    assert (
        client.put(f"/api/projects/{project}/uploads/..%2Fx.txt", content=b"x").status_code == 400
    )
    sneaky = client.get(f"/api/projects/{project}/out/..%2Fopportunity.json")
    assert sneaky.status_code in (400, 404)
    assert client.get("/api/projects/..%2F..%2Fconfig").status_code in (400, 404)
    missing = client.post(f"/api/chats/{chat}/messages", json={"text": "hi", "files": ["nope.pdf"]})
    assert "Upload missing" in reply_text(events(missing)) or "error" in missing.text


def test_title_from_message_or_file() -> None:
    assert title_from("  when is it   due? ", []) == "when is it due?"
    assert title_from("", ["acme_rfp-2026.pdf"]) == "acme rfp 2026"
    assert title_from("/digest", ["a.pdf"]) == "a"
    assert title_from("x" * 80, []).endswith("…")


# --- workspace, trust, token, folders, models (phase 12) ----------------------------------


def test_needs_a_trusted_workspace_first(home: Path, tmp_path: Path) -> None:
    _, llm = make(home)
    server, base = serve(home, llm)
    try:
        with httpx.Client(base_url=base, timeout=30) as c:
            blocked = c.get("/api/projects")
            assert blocked.status_code == 409 and blocked.json()["needs_workspace"] is True
            target = tmp_path / "Bids" / "Acme"
            ask = c.post("/api/workspace", json={"path": str(target)})
            assert ask.status_code == 400 and ask.json()["needs_trust"] == str(target.resolve())
            assert not target.exists()  # nothing is created before trust
            opened = c.post("/api/workspace", json={"path": str(target), "trust": True}).json()
            assert opened["active"] == str(target.resolve())
            assert (target / ".studio" / "workspace.json").exists()
            project = c.post("/api/projects", json={"name": "Acme"}).json()["project"]["id"]
            assert (target / "projects" / project / "opportunity.json").exists()
            assert not (home / "workspace").exists()  # nothing written to the app folder
            assert c.get("/api/workspace").json()["trusted"][0]["path"] == str(target.resolve())
            assert c.post("/api/workspace", json={"path": "/", "trust": True}).status_code == 400
            gone = c.post("/api/workspace/forget", json={"path": str(target)}).json()
            assert gone["active"] is None and c.get("/api/projects").status_code == 409
    finally:
        server.shutdown()
        server.server_close()


def test_token_cookie_and_header_required(home: Path, ws: Path) -> None:
    _, llm = make(home)
    server, base = serve(home, llm, workspace=ws, token="s3cret")
    port = server.server_address[1]
    try:
        with httpx.Client(base_url=base, timeout=30) as c:
            assert c.get("/api/health").status_code == 401
            wrong = c.get("/?t=nope", follow_redirects=False)
            assert wrong.status_code == 302 and "set-cookie" not in wrong.headers
            ok = c.get("/?t=s3cret", follow_redirects=False)
            cookie = ok.headers["set-cookie"]
            assert f"studio_{port}=s3cret" in cookie and "HttpOnly" in cookie
            assert "SameSite=Strict" in cookie
            assert c.get("/api/health").status_code == 200  # reads: the cookie is enough
            assert c.post("/api/projects", json={"name": "x"}).status_code == 401  # writes: +header
            made = c.post("/api/projects", json={"name": "x"}, headers={"X-Studio": "1"})
            assert made.status_code == 201
            assert c.get("/").status_code == 200  # the page itself needs no token
    finally:
        server.shutdown()
        server.server_close()


def test_folder_browser_lists_and_creates(client: httpx.Client, tmp_path: Path) -> None:
    tmp_path = tmp_path / "browse"
    (tmp_path / "Bids").mkdir(parents=True)
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x")
    listing = client.get("/api/fs", params={"path": str(tmp_path)}).json()
    assert listing["dirs"] == ["Bids"] and listing["parent"]
    made = client.post("/api/fs/mkdir", json={"path": str(tmp_path / "Bids"), "name": "Acme"})
    assert made.status_code == 201 and (tmp_path / "Bids" / "Acme").is_dir()
    for bad in ("../x", ".x", "a/b", ""):
        r = client.post("/api/fs/mkdir", json={"path": str(tmp_path), "name": bad})
        assert r.status_code == 400
    assert client.get("/api/fs", params={"path": "relative"}).status_code == 404


class ModelsLLM:
    """FakeLLM stand-in that also reports models."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def model_details(self) -> list[dict]:
        return [
            {"name": "qwen3:8b", "size": 5_200_000_000, "loaded": True},
            {"name": "qwen3:4b", "size": 2_600_000_000, "loaded": False},
            {"name": "huge:70b", "size": 40_000_000_000, "loaded": False},
            {"name": "nomic-embed-text:latest", "size": 270_000_000, "loaded": False},
        ]


def test_models_list_and_role_change(home: Path, ws: Path, monkeypatch) -> None:
    from studio import sysinfo

    monkeypatch.setattr(sysinfo, "total_ram_bytes", lambda: 16 * 1024**3)
    _, llm = make(home)
    server, base = serve(home, ModelsLLM(llm), workspace=ws)
    try:
        with httpx.Client(base_url=base, timeout=30) as c:
            info = c.get("/api/models").json()
            by_name = {m["name"]: m for m in info["models"]}
            assert info["ollama"] is True and info["roles"]["worker"] == "qwen3:8b"
            assert by_name["qwen3:8b"]["roles"] == ["worker"] and by_name["qwen3:8b"]["fits"]
            assert by_name["huge:70b"]["fits"] is False
            assert by_name["nomic-embed-text:latest"]["roles"] == ["embed"]  # untagged = :latest
            assert (
                c.post("/api/models/role", json={"role": "worker", "model": "x:1b"}).status_code
                == 400
            )
            assert (
                c.post("/api/models/role", json={"role": "boss", "model": "qwen3:4b"}).status_code
                == 400
            )
            changed = c.post("/api/models/role", json={"role": "worker", "model": "qwen3:4b"})
            assert changed.json()["roles"]["worker"] == "qwen3:4b"
            assert "qwen3:4b" in (home / "config" / "overrides.yaml").read_text()
    finally:
        server.shutdown()
        server.server_close()


def test_chat_cannot_change_agent_commands(client: httpx.Client) -> None:
    _, chat = new_project(client, "Acme")
    evts = events(
        client.post(
            f"/api/chats/{chat}/messages",
            json={"text": '/config set agents.agents.opencode.plan_cmd ["sh","-c","id"]'},
        )
    )
    assert "can't be changed from chat" in reply_text(evts)
