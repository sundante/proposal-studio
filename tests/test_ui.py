"""Studio UI server: real HTTP on a free port, FakeLLM, synthetic Acme fixtures."""

import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from studio.ui.server import make_server
from studio.ui.store import title_from
from tests.test_router import make

REVEALED: list[Path] = []


def serve(app_root: Path, llm, **kwargs) -> tuple[ThreadingHTTPServer, str]:
    kwargs.setdefault("reveal_fn", REVEALED.append)  # never open a real file manager in tests
    server = make_server(app_root, lambda: llm, port=0, **kwargs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def home(studio_home: Path) -> Path:
    from tests.test_router import home as router_home

    return router_home.__wrapped__(studio_home)


@pytest.fixture
def ws(home: Path) -> Path:
    """The Proposal Studio folder (library + project list); config stays in ``home``."""
    return home.parent / f"{home.name}-Proposal Studio"


@pytest.fixture
def client(home: Path, ws: Path) -> Iterator[httpx.Client]:
    _, llm = make(home)
    server, base = serve(home, llm, home=ws)
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
    resp = client.post("/api/projects", json={"name": name, "trust": True})
    assert resp.status_code == 201
    data = resp.json()
    return data["project"]["id"], data["chat"]["id"]


def test_serves_the_app(client: httpx.Client) -> None:
    page = client.get("/")
    assert page.status_code == 200 and "<title>Proposal Studio</title>" in page.text
    assert client.get("/js/main.js").headers["content-type"].startswith("text/javascript")
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
    folder = ws / "Acme Health Plan RFP"  # a readable folder, named after the project
    assert not list((folder / ".uploads").glob("*"))  # cleaned up
    assert (folder / "input" / "acme_rfp.pdf").exists() and (folder / "chats").is_dir()

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


def test_new_project_asks_for_trust_and_shows_its_folder(
    client: httpx.Client, ws, tmp_path
) -> None:
    assert client.post("/api/projects", json={"name": "Acme"}).status_code == 400  # no trust
    made = client.post("/api/projects", json={"name": "Acme", "trust": True}).json()["project"]
    assert made["path"] == str((ws / "Acme").resolve())
    chosen = tmp_path / "Bids" / "Example Hospital"
    other = client.post(
        "/api/projects", json={"name": "Example", "folder": str(chosen), "trust": True}
    ).json()["project"]
    assert other["path"] == str(chosen.resolve()) and (chosen / "opportunity.json").exists()
    for bad in (str(ws), str(ws / "library"), str(chosen / "sub"), "/", "relative"):
        r = client.post("/api/projects", json={"name": "x", "folder": bad, "trust": True})
        assert r.status_code == 400, bad
    listed = {p["id"]: p for p in client.get("/api/projects").json()}
    assert listed[other["id"]]["path"] == str(chosen.resolve())
    settings = client.get("/api/settings").json()
    assert settings["home"] == str(ws) and settings["library"] == str(ws / "library")


def test_delete_project_keep_or_delete_files(client: httpx.Client, tmp_path: Path) -> None:
    folder = tmp_path / "Bids" / "Acme"
    pid = client.post(
        "/api/projects", json={"name": "Acme", "folder": str(folder), "trust": True}
    ).json()["project"]["id"]
    kept = client.delete(f"/api/projects/{pid}").json()
    assert kept["files_deleted"] is False and folder.is_dir()  # removed from the list only
    assert pid not in {p["id"] for p in client.get("/api/projects").json()}
    back = client.post(
        "/api/projects", json={"name": "ignored", "folder": str(folder), "trust": True}
    ).json()  # an existing project folder is added back, with its chats
    assert back["project"]["path"] == str(folder.resolve())
    gone = client.delete(f"/api/projects/{back['project']['id']}?files=delete").json()
    assert gone["files_deleted"] is True and not folder.exists()
    assert client.delete("/api/projects/nope").status_code in (400, 404)


def test_missing_project_folder_is_listed_and_removable(client: httpx.Client, tmp_path) -> None:
    import shutil

    folder = tmp_path / "Gone"
    pid = client.post(
        "/api/projects", json={"name": "Gone", "folder": str(folder), "trust": True}
    ).json()["project"]["id"]
    shutil.rmtree(folder)  # deleted outside the app
    entry = next(p for p in client.get("/api/projects").json() if p["id"] == pid)
    assert entry["missing"] is True
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert all(p["id"] != pid for p in client.get("/api/projects").json())


def test_open_folder_buttons(client: httpx.Client, ws: Path) -> None:
    REVEALED.clear()
    pid, _ = new_project(client, "Acme")
    assert client.post(f"/api/projects/{pid}/reveal").json()["path"] == str((ws / "Acme").resolve())
    assert client.post("/api/library/reveal").json()["path"] == str(ws / "library")
    assert client.post("/api/home/reveal").json()["path"] == str(ws)
    assert [(ws / "Acme").resolve(), ws / "library", ws] == REVEALED


def test_change_the_proposal_studio_folder(client: httpx.Client, tmp_path: Path) -> None:
    target = tmp_path / "Elsewhere" / "Proposal Studio"
    assert client.post("/api/settings/home", json={"path": str(target)}).status_code == 400
    moved = client.post("/api/settings/home", json={"path": str(target), "trust": True}).json()
    assert moved["home"] == str(target.resolve()) and (target / "library").is_dir()
    assert client.get("/api/projects").json() == []  # a fresh folder has no projects yet


def test_token_cookie_and_header_required(home: Path, ws: Path) -> None:
    _, llm = make(home)
    server, base = serve(home, llm, home=ws, token="s3cret")
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
            made = c.post(
                "/api/projects", json={"name": "x", "trust": True}, headers={"X-Studio": "1"}
            )
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
    server, base = serve(home, ModelsLLM(llm), home=ws)
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


def test_static_subfolders_and_types(client: httpx.Client) -> None:
    js = client.get("/js/main.js")
    assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
    assert client.get("/css/tokens.css").headers["content-type"].startswith("text/css")
    import http.client
    from urllib.parse import urlparse

    url = urlparse(str(client.base_url))
    for bad in ("/js/../index.html", "/js/%2e%2e/index.html", "/.hidden.js", "/js/x.py", "/js/"):
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
        conn.request("GET", bad)  # raw path: no client-side normalisation of ".."
        assert conn.getresponse().status == 404, bad
        conn.close()


def test_folder_places_and_description(client: httpx.Client, tmp_path: Path, ws: Path) -> None:
    listing = client.get("/api/fs", params={"path": str(tmp_path)}).json()
    labels = {p["label"]: p["path"] for p in listing["places"]}
    assert labels["Proposal Studio"] == str(ws) and listing["studio_home"] == str(ws)
    pid, _ = new_project(client, "Acme")
    out = client.patch(f"/api/projects/{pid}", json={"description": "Medicaid AI platform"}).json()
    assert out["description"] == "Medicaid AI platform" and out["title"] == "Acme"
