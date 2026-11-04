"""The Studio UI: a local chat app over the router, served with the Python standard library.

``studio ui`` starts a :class:`ThreadingHTTPServer` on 127.0.0.1 that serves the single-page app
in ``static/`` and a small JSON API. Message replies stream as Server-Sent Events: ``status``
(progress line), ``chunk`` (reply text), ``pending`` (an action waits for Approve/Reject) and
``done`` (files produced). Nothing is fetched from the internet; there is no telemetry.

Each **project** lives in a folder the user chose and trusted; the *Proposal Studio folder*
(``home``) holds the shared ``library/`` and the list of projects (see :mod:`studio.session`).
Config and templates come from the app folder. With a per-launch ``token``, every ``/api/*``
request needs the session cookie (set by visiting ``/?t=<token>``); writes also need an
``X-Studio: 1`` header.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from studio import __version__, sysinfo, trust
from studio import config as cfgmod
from studio import digest as digestmod
from studio import session as sessmod
from studio.deck.writer import DECK_FILE
from studio.guards import GuardError, check_model_allowed, resolve_in_sandbox, scan_phi
from studio.llm import LLMClient
from studio.rag import VectorIndex
from studio.router import Router, RouterContext
from studio.ui.store import (
    ChatMessage,
    ChatStore,
    StoreError,
    now,
    safe_name,
    title_from,
    uploads_dir,
)

STATIC = Path(__file__).parent / "static"
# Explicit types: on Windows the registry can map .js to text/plain, which breaks module scripts.
STATIC_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}
MAX_UPLOAD = 200 * 1024 * 1024
MAX_JSON = 1024 * 1024
Send = Callable[[str, dict[str, Any]], None]


class ApiError(Exception):
    """An HTTP error with a user-facing message."""

    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra


def tagged(model: str) -> str:
    """Ollama names without a tag mean ``:latest`` (``nomic-embed-text`` = ``…:latest``)."""
    return model if ":" in model else f"{model}:latest"


def reveal(path: Path) -> None:
    """Show ``path`` in the file manager (Finder, Explorer, or the desktop's default)."""
    if sys.platform == "darwin":
        cmd = ["open", str(path)]
    elif sys.platform == "win32":
        cmd = ["explorer", str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603


@dataclass
class StudioApp:
    """Everything the request handler needs; one per server."""

    app_root: Path  # config/ and templates/
    llm_factory: Callable[[], LLMClient]
    home: Path  # the Proposal Studio folder: library/ + .studio/ (project list, sessions)
    token: str | None = None  # per-launch API token (None: no token check, e.g. tests)
    reveal: Callable[[Path], None] = reveal
    # Builds a client for a per-chat model/thinking choice (None: overrides are ignored).
    llm_for: Callable[[cfgmod.ModelsConfig], LLMClient] | None = None
    router: Router = field(init=False)
    chats: ChatStore = field(init=False)
    _locks: dict[str, threading.Lock] = field(default_factory=dict, init=False)
    _locks_guard: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self.set_home(self.home)

    def set_home(self, folder: Path) -> None:
        """Use ``folder`` as the Proposal Studio folder (created if missing)."""
        sessmod.init_home(folder)
        ctx = RouterContext(
            folder,
            self.llm_factory,
            allow_local_paths=False,
            app_root=self.app_root,
            allow_agent_config=False,
        )
        self.home = folder
        self.router = Router(ctx)
        self.chats = ChatStore(folder)
        self.chats.purge_temporary()  # temporary chats never outlive a session
        with self._locks_guard:
            self._locks.clear()

    @property
    def root(self) -> Path:
        return self.home

    def settings(self) -> dict[str, Any]:
        return {
            "home": str(self.home),
            "library": str(self.home / sessmod.LIBRARY_DIR),
            "user_dir": str(trust.user_dir()),
            "name": trust.user_name(),
            "user_home": str(Path.home()),
            "sep": "\\" if sys.platform == "win32" else "/",
        }

    def models(self) -> dict[str, Any]:
        """Pulled and loaded models, role assignments and whether each fits this machine."""
        cfg = cfgmod.load_config(self.app_root)
        roles = {name: tagged(rc.model) for name, rc in cfg.models.roles.items()}
        ram = sysinfo.total_ram_bytes()
        info: dict[str, Any] = {
            "roles": roles,
            "think": cfg.models.think,
            "ram": ram,
            "ollama": None,
            "models": [],
        }
        fn = getattr(self.llm_factory(), "model_details", None)
        if fn is None:
            return info
        try:
            details = fn()
        except Exception:  # noqa: BLE001 - any failure means Ollama isn't reachable
            info["ollama"] = False
            return info
        info["ollama"] = True
        budget = sysinfo.model_budget(ram)
        for m in details:
            m["roles"] = [r for r, model in roles.items() if model == tagged(m["name"])]
            m["fits"] = None if budget is None else m["size"] * 1.2 <= budget
        info["models"] = details
        return info

    def apply_prefs(self, chat: Any, body: dict[str, Any]) -> None:
        """Remember the composer's mode / model / thinking choices on the chat."""
        prefs = chat.prefs
        if "mode" in body:
            mode = str(body["mode"])
            if mode not in ("auto", "ask", "research", "chat", "draft"):
                raise ApiError(HTTPStatus.BAD_REQUEST, f"Unknown mode '{mode}'.")
            prefs.mode = mode
        if "model" in body:
            model = str(body["model"] or "").strip()
            if model:
                cfg = cfgmod.load_config(self.app_root)
                try:
                    check_model_allowed(model, block_cloud=cfg.models.block_cloud_models)
                except GuardError as exc:
                    raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
            prefs.model = model
        if "think" in body:
            prefs.think = None if body["think"] is None else bool(body["think"])

    def factory_for(self, chat: Any) -> Callable[[], LLMClient] | None:
        """An LLM factory honouring the chat's model/thinking choice (None = the default)."""
        prefs = chat.prefs
        if self.llm_for is None or (not prefs.model and prefs.think is None):
            return None
        models = cfgmod.load_config(self.app_root).models
        roles = dict(models.roles)
        if prefs.model:
            roles["worker"] = roles["worker"].model_copy(update={"model": prefs.model})
        update: dict[str, Any] = {"roles": roles}
        if prefs.think is not None:
            update["think"] = prefs.think
        chosen = models.model_copy(update=update)
        make = self.llm_for
        return lambda: make(chosen)

    def lock(self, project: str) -> threading.Lock:
        """One message at a time per project (the index and outputs are shared)."""
        with self._locks_guard:
            return self._locks.setdefault(project, threading.Lock())

    # -- projects --

    def opp(self, project: str) -> sessmod.Opportunity:
        try:
            return sessmod.get_opportunity(self.root, project)
        except sessmod.SessionError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, str(exc)) from exc

    def projects(self) -> list[dict[str, Any]]:
        out = []
        for opp in sessmod.list_opportunities(self.root):
            chats = self.chats.list(opp.id)
            out.append(
                {
                    "id": opp.id,
                    "title": opp.title or opp.id,
                    "description": opp.description,
                    "path": str(opp.path),
                    "missing": False,
                    "files": len([p for p in (opp.path / "input").glob("*") if p.is_file()]),
                    "created": opp.created,
                    "updated": chats[0].updated if chats else opp.created,
                    "chats": [c.summary() for c in chats],
                }
            )
        out.sort(key=lambda p: p["updated"], reverse=True)
        for opp_id, path, ok in sessmod.registry_entries(self.root):
            if not ok:  # moved or deleted outside the app: shown so it can be removed
                out.append(
                    {"id": opp_id, "title": path.name or opp_id, "path": str(path),
                     "missing": True, "created": "", "updated": "", "chats": []}
                )  # fmt: skip
        return out

    def project(self, project: str) -> dict[str, Any]:
        opp = self.opp(project)
        info = sessmod.opportunity_status(opp)
        input_dir = opp.path / "input"
        files = sorted(p.name for p in input_dir.glob("*") if p.is_file())
        return {
            "id": opp.id,
            "title": opp.title or opp.id,
            "description": opp.description,
            "path": str(opp.path),
            "status": info,
            "files": [{"name": n, "chunks": info["files"].get(n, 0)} for n in files],
            "chats": [c.summary() for c in self.chats.list(opp.id)],
        }

    def remove_file(self, project: str, name: str) -> None:
        opp = self.opp(project)
        with self.lock(project):
            path = safe_name(opp.path / "input", name)
            path.unlink(missing_ok=True)
            index = VectorIndex(opp.path / "index")
            if name in index.files():
                index.remove_file(name)
                index.save()

    # -- messages --

    def run_message(self, chat_id: str, body: dict[str, Any], send: Send) -> None:
        """Handle one chat message, streaming events through ``send``."""
        chat = self.chats.get(chat_id)
        opp = self.opp(chat.project)
        text = str(body.get("text") or "").strip()
        display = str(body.get("display") or text).strip()
        steps = [str(s) for s in body.get("steps") or []] or [text]
        names = [str(n) for n in body.get("files") or []]
        staged = uploads_dir(opp)
        files = [safe_name(staged, n) for n in names]
        missing = [p.name for p in files if not p.exists()]
        if missing:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Upload missing: {', '.join(missing)}")
        if not display and not files:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Empty message.")
        self.apply_prefs(chat, body)
        factory = self.factory_for(chat)
        history = chat.history(turns=8)

        with self.lock(opp.id):
            if not chat.messages:
                chat.title = title_from(display, names)
            chat.messages.append(ChatMessage(role="user", content=display, files=names))
            chat.updated = now()
            self.chats.save(chat)
            send("chat", chat.summary())

            sess = self.router.session(f"ui-{chat.id}")
            sess.active_opp = opp.id
            sess.last_outputs.pop("produced", None)
            reply: list[str] = []

            def chunk(piece: str) -> None:
                reply.append(piece)
                send("chunk", {"text": piece})

            hits = scan_phi(display)
            if hits:
                kinds = ", ".join(sorted({h.kind for h in hits}))
                chunk(f"⚠ Possible PHI in your message ({kinds}). Don't paste patient data.\n\n")

            def emit(event: dict[str, Any]) -> None:
                data = event.get("data") or {}
                if not data.get("done"):
                    send("status", {"text": data.get("description", "")})

            async def go() -> None:
                for i, step in enumerate(steps):
                    if i:
                        chunk("\n\n---\n\n")
                    failed = False
                    attached = files if i == 0 else []
                    stream = self.router.handle(
                        step,
                        attached,
                        sess,
                        emit,
                        mode=chat.prefs.mode,
                        history=history,
                        llm_factory=factory,
                    )
                    async for piece in stream:
                        failed = failed or piece.lstrip().startswith("⚠")
                        chunk(piece)
                    if failed or "pending" in sess.last_outputs:
                        break

            asyncio.run(go())

            out_dir = (opp.path / "out").resolve()
            outputs = [
                Path(item).name
                for item in sess.last_outputs.pop("produced", [])
                if Path(item).is_file() and Path(item).resolve().parent == out_dir
            ]
            pending = sess.last_outputs.get("pending")
            self.router.store.save(sess)
            chat.messages.append(
                ChatMessage(role="assistant", content="".join(reply), outputs=outputs)
            )
            chat.updated = now()
            self.chats.save(chat)

            keep = {Path(p).name for p in (pending or {}).get("attachments", [])}
            for path in files:
                if path.name not in keep:
                    path.unlink(missing_ok=True)

        if pending:
            send("pending", {"command": pending["command"]})
        send("done", {"outputs": outputs})


class Handler(BaseHTTPRequestHandler):
    """Routes requests to :class:`StudioApp`."""

    app: StudioApp  # set on the subclass made by make_server
    server_version = f"ProposalStudio/{__version__}"
    protocol_version = "HTTP/1.1"

    ROUTES: list[tuple[str, re.Pattern[str], str]] = [
        (m, re.compile(f"^{p}$"), h)
        for m, p, h in [
            ("GET", r"/api/health", "health"),
            ("GET", r"/api/settings", "get_settings"),
            ("POST", r"/api/settings/home", "set_home"),
            ("POST", r"/api/settings/profile", "set_profile"),
            ("GET", r"/api/search", "search"),
            ("POST", r"/api/library/reveal", "reveal_library"),
            ("POST", r"/api/home/reveal", "reveal_home"),
            ("GET", r"/api/fs", "list_dirs"),
            ("POST", r"/api/fs/mkdir", "make_dir"),
            ("GET", r"/api/models", "get_models"),
            ("POST", r"/api/models/role", "set_role_model"),
            ("GET", r"/api/projects", "list_projects"),
            ("POST", r"/api/projects", "create_project"),
            ("GET", r"/api/projects/([^/]+)", "get_project"),
            ("PATCH", r"/api/projects/([^/]+)", "rename_project"),
            ("DELETE", r"/api/projects/([^/]+)", "delete_project"),
            ("POST", r"/api/projects/([^/]+)/reveal", "reveal_project"),
            ("POST", r"/api/projects/([^/]+)/chats", "create_chat"),
            ("PUT", r"/api/projects/([^/]+)/uploads/([^/]+)", "upload"),
            ("DELETE", r"/api/projects/([^/]+)/files/([^/]+)", "delete_file"),
            ("GET", r"/api/projects/([^/]+)/digest", "get_digest"),
            ("GET", r"/api/projects/([^/]+)/deck", "get_deck"),
            ("GET", r"/api/projects/([^/]+)/out/([^/]+)", "download"),
            ("GET", r"/api/chats", "recent_chats"),
            ("GET", r"/api/chats/([0-9a-f]+)", "get_chat"),
            ("PATCH", r"/api/chats/([0-9a-f]+)", "rename_chat"),
            ("DELETE", r"/api/chats/([0-9a-f]+)", "delete_chat"),
            ("POST", r"/api/chats/([0-9a-f]+)/messages", "post_message"),
        ]
    ]

    # -- plumbing --

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Quiet: no per-request logging."""

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _local_request(self, method: str) -> bool:
        """Block DNS rebinding (Host) and cross-site writes (Origin)."""
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        if self.headers.get("Host", "") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return method == "GET" or not origin or urlparse(origin).netloc in allowed

    @property
    def _cookie_name(self) -> str:
        return f"studio_{self.server.server_address[1]}"

    def _authorised(self, method: str) -> bool:
        """Per-launch token in a ``SameSite=Strict`` cookie (never sent cross-site); writes also
        need an ``X-Studio: 1`` header, which a cross-site form can't add."""
        token = self.app.token
        if token is None:
            return True
        sent = SimpleCookie(self.headers.get("Cookie", "")).get(self._cookie_name)
        if sent is None or not hmac.compare_digest(sent.value, token):
            return False
        return method == "GET" or self.headers.get("X-Studio") == "1"

    def _dispatch(self, method: str) -> None:
        path = urlparse(self.path).path
        try:
            if not self._local_request(method):
                raise ApiError(HTTPStatus.FORBIDDEN, "Only local requests are allowed.")
            if path.startswith("/api/") and not self._authorised(method):
                raise ApiError(
                    HTTPStatus.UNAUTHORIZED,
                    "Open Proposal Studio from the link `studio ui` printed in the terminal.",
                    needs_login=True,
                )
            if not path.startswith("/api/"):
                if method != "GET":
                    raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "Not allowed.")
                self._static(path)
                return
            for m, pattern, name in self.ROUTES:
                match = pattern.match(path)
                if match and m == method:
                    getattr(self, f"api_{name}")(*(unquote(g) for g in match.groups()))
                    return
            raise ApiError(HTTPStatus.NOT_FOUND, "Not found.")
        except ApiError as exc:
            self._json({"error": str(exc), **exc.extra}, exc.status)
        except trust.TrustError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (StoreError, sessmod.SessionError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if status >= 400:  # the request body may be unread: don't reuse the connection
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, *, download: bool = False) -> None:
        data = path.read_bytes()
        ctype = STATIC_TYPES.get(path.suffix.lower()) or (
            mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        )
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(data)

    def _body(self, limit: int) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Too large.")
        return self.rfile.read(length) if length else b""

    def _payload(self) -> dict[str, Any]:
        raw = self._body(MAX_JSON)
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Invalid JSON.") from exc
        if not isinstance(data, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Expected a JSON object.")
        return data

    def _static(self, path: str) -> None:
        offered = parse_qs(urlparse(self.path).query).get("t", [""])[0]
        if path in ("", "/") and offered and self.app.token:
            self.send_response(HTTPStatus.FOUND)
            if hmac.compare_digest(offered, self.app.token):
                self.send_header(
                    "Set-Cookie",
                    f"{self._cookie_name}={self.app.token}; HttpOnly; SameSite=Strict; Path=/",
                )
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        parts = rel.split("/")
        bad = any(p in ("", ".", "..") or p.startswith(".") or "\\" in p for p in parts)
        if bad or Path(rel).suffix.lower() not in STATIC_TYPES:
            raise ApiError(HTTPStatus.NOT_FOUND, "Not found.")
        try:
            target = resolve_in_sandbox(STATIC, rel)
        except GuardError as exc:
            raise ApiError(HTTPStatus.NOT_FOUND, "Not found.") from exc
        if not target.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "Not found.")
        self._file(target)

    # -- API --

    def api_health(self) -> None:
        loaded: list[str] | None = None
        ollama: bool | None = None
        try:
            fn = getattr(self.app.llm_factory(), "loaded_models", None)
            if fn is not None:
                loaded = fn()
                ollama = loaded is not None
        except Exception:  # noqa: BLE001 - any failure means "not reachable"
            ollama = False
        self._json(
            {
                "version": __version__,
                "ollama": ollama,
                "loaded": loaded or [],
                "home": str(self.app.home),
            }
        )

    def api_get_settings(self) -> None:
        self._json(self.app.settings())

    def api_set_profile(self) -> None:
        trust.set_user_name(str(self._payload().get("name") or ""))
        self._json(self.app.settings())

    def api_search(self) -> None:
        q = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
        projects = []
        if q:
            low = q.lower()
            projects = [
                {"id": p["id"], "title": p["title"], "path": p["path"]}
                for p in self.app.projects()
                if not p["missing"]
                and (low in p["title"].lower() or low in (p.get("description") or "").lower())
            ][:10]
        self._json({"query": q, "projects": projects, "chats": self.app.chats.search(q)})

    def api_set_home(self) -> None:
        body = self._payload()
        if body.get("trust") is not True:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Confirm that you trust this folder.")
        self.app.set_home(trust.set_home(str(body.get("path") or "")))
        self._json(self.app.settings())

    def api_reveal_home(self) -> None:
        self.app.reveal(self.app.home)
        self._json({"path": str(self.app.home)})

    def api_reveal_library(self) -> None:
        folder = self.app.home / sessmod.LIBRARY_DIR
        folder.mkdir(parents=True, exist_ok=True)
        self.app.reveal(folder)
        self._json({"path": str(folder)})

    def api_list_dirs(self) -> None:
        raw = parse_qs(urlparse(self.path).query).get("path", [""])[0]
        folder = Path(raw).expanduser() if raw else Path.home()
        if not folder.is_absolute() or not folder.is_dir():
            raise ApiError(HTTPStatus.NOT_FOUND, f"No folder {raw}.")
        folder = folder.resolve()
        try:
            dirs = sorted(
                (p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=str.lower,
            )[:500]
        except PermissionError as exc:
            raise ApiError(HTTPStatus.FORBIDDEN, f"Can't open {folder}.") from exc
        self._json(
            {
                "path": str(folder),
                "parent": str(folder.parent) if folder.parent != folder else None,
                "dirs": dirs,
                "project": (folder / sessmod.OPP_FILE).is_file(),
                "empty": not any(folder.iterdir()),
                "home": str(Path.home()),
                "places": self._places(),
                "studio_home": str(self.app.home),
            }
        )

    def _places(self) -> list[dict[str, str]]:
        """Quick locations for the folder picker (only those that exist)."""
        home = Path.home()
        candidates = [
            ("Home", home),
            ("Documents", home / "Documents"),
            ("Desktop", home / "Desktop"),
            ("Downloads", home / "Downloads"),
            ("Proposal Studio", self.app.home),
        ]
        return [{"label": label, "path": str(p)} for label, p in candidates if p.is_dir()]

    def api_make_dir(self) -> None:
        body = self._payload()
        parent = Path(str(body.get("path") or "")).expanduser()
        name = str(body.get("name") or "").strip()
        if not parent.is_absolute() or not parent.is_dir():
            raise ApiError(HTTPStatus.NOT_FOUND, "Pick a folder first.")
        if not name or name in (".", "..") or Path(name).name != name or name.startswith("."):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Use a plain folder name.")
        target = parent.resolve() / name
        target.mkdir(exist_ok=True)
        self._json({"path": str(target)}, 201)

    def api_get_models(self) -> None:
        self._json(self.app.models())

    def api_set_role_model(self) -> None:
        body = self._payload()
        role, model = str(body.get("role") or ""), str(body.get("model") or "").strip()
        if role not in ("router", "worker", "embed") or not model:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "Choose a role (router, worker, embed) and model."
            )
        pulled = {m["name"] for m in self.app.models()["models"]}
        if pulled and tagged(model) not in {tagged(n) for n in pulled}:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, f"{model} isn't pulled. Run `ollama pull {model}`."
            )
        try:
            cfgmod.set_value(f"models.roles.{role}.model", model, self.app.app_root)
        except cfgmod.ConfigError as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
        self._json(self.app.models())

    def api_list_projects(self) -> None:
        self._json(self.app.projects())

    def api_create_project(self) -> None:
        """New project in a trusted folder (default: a new folder in the Proposal Studio folder).

        A folder that already holds a project is added back to the list instead.
        """
        body = self._payload()
        if body.get("trust") is not True:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Confirm that you trust the project folder.")
        name = str(body.get("name") or "").strip() or "Untitled project"
        raw = str(body.get("folder") or "").strip()
        folder = trust.check_candidate(raw) if raw else None
        if folder is not None and (folder / sessmod.OPP_FILE).is_file():
            opp = sessmod.import_project(self.app.root, folder)
            chats = self.app.chats.list(opp.id)
            chat = chats[0] if chats else self.app.chats.create(opp.id)
        else:
            opp = sessmod.create_project(self.app.root, name, folder)
            chat = self.app.chats.create(opp.id)
        self._json({"project": self.app.project(opp.id), "chat": chat.model_dump()}, 201)

    def api_get_project(self, project: str) -> None:
        self._json(self.app.project(project))

    def api_rename_project(self, project: str) -> None:
        opp = self.app.opp(project)
        body = self._payload()
        title = str(body["title"]) if "title" in body else opp.title
        description = str(body["description"]) if "description" in body else None
        sessmod.rename_opportunity(self.app.root, project, title, description)
        self._json(self.app.project(project))

    def api_delete_project(self, project: str) -> None:
        delete_files = parse_qs(urlparse(self.path).query).get("files", [""])[0] == "delete"
        with self.app.lock(project):
            path = sessmod.remove_project(self.app.root, project, delete_files=delete_files)
        self._json({"deleted": project, "path": str(path), "files_deleted": delete_files})

    def api_reveal_project(self, project: str) -> None:
        opp = self.app.opp(project)
        self.app.reveal(opp.path)
        self._json({"path": str(opp.path)})

    def api_create_chat(self, project: str) -> None:
        self.app.opp(project)
        temporary = bool(self._payload().get("temporary"))
        if temporary:
            self.app.chats.purge_temporary()  # only one temporary chat at a time
        self._json(self.app.chats.create(project, temporary=temporary).model_dump(), 201)

    def api_upload(self, project: str, name: str) -> None:
        opp = self.app.opp(project)
        folder = uploads_dir(opp)
        folder.mkdir(parents=True, exist_ok=True)
        target = safe_name(folder, name)
        target.write_bytes(self._body(MAX_UPLOAD))
        self._json({"name": target.name, "size": target.stat().st_size}, 201)

    def api_delete_file(self, project: str, name: str) -> None:
        self.app.remove_file(project, name)
        self._json(self.app.project(project))

    def api_get_digest(self, project: str) -> None:
        opp = self.app.opp(project)
        digest = digestmod.load_digest(opp.path)
        if digest is None:
            raise ApiError(HTTPStatus.NOT_FOUND, "No RFP summary yet.")
        self._json({"digest": digest.model_dump(), "stale": digestmod.is_stale(opp.path)})

    def api_get_deck(self, project: str) -> None:
        path = self.app.opp(project).path / DECK_FILE
        if not path.exists():
            raise ApiError(HTTPStatus.NOT_FOUND, "No slides yet.")
        self._json(json.loads(path.read_text(encoding="utf-8")))

    def api_download(self, project: str, name: str) -> None:
        target = safe_name(self.app.opp(project).path / "out", name)
        if not target.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "No such file.")
        self._file(target, download=True)

    def api_recent_chats(self) -> None:
        self._json([c.summary() for c in self.app.chats.recent()])

    def api_get_chat(self, chat_id: str) -> None:
        chat = self.app.chats.get(chat_id)
        sess = self.app.router.session(f"ui-{chat.id}")
        pending = sess.last_outputs.get("pending")
        self._json({**chat.model_dump(), "pending": pending["command"] if pending else None})

    def api_rename_chat(self, chat_id: str) -> None:
        chat = self.app.chats.get(chat_id)
        body = self._payload()
        if "title" in body:
            chat.title = str(body.get("title") or "").strip() or chat.title
        if "pinned" in body:
            chat.pinned = bool(body["pinned"])
        if "temporary" in body and not body["temporary"]:
            chat.temporary = False  # "keep this chat"
        self.app.chats.save(chat)
        self._json(chat.summary())

    def api_delete_chat(self, chat_id: str) -> None:
        self.app.chats.delete(chat_id)
        self._json({"deleted": chat_id})

    def api_post_message(self, chat_id: str) -> None:
        body = self._payload()
        self.app.chats.get(chat_id)  # 404-equivalent before the stream starts
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        gone = False

        def send(event: str, data: dict[str, Any]) -> None:
            nonlocal gone
            if gone:
                return  # the browser stopped listening; keep working, save the reply
            try:
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                gone = True

        try:
            self.app.run_message(chat_id, body, send)
        except (ApiError, StoreError, sessmod.SessionError) as exc:
            send("error", {"text": str(exc)})


def make_server(
    app_root: Path,
    llm_factory: Callable[[], LLMClient],
    port: int = 8765,
    *,
    home: Path,
    token: str | None = None,
    reveal_fn: Callable[[Path], None] = reveal,
    llm_for: Callable[[cfgmod.ModelsConfig], LLMClient] | None = None,
) -> ThreadingHTTPServer:
    """A ready-to-serve UI server on 127.0.0.1:``port`` (0 picks a free port).

    ``home`` is the Proposal Studio folder (created if missing). ``token`` (``studio ui`` passes a
    random one) protects the API; see :class:`Handler`.
    """
    app = StudioApp(
        app_root, llm_factory, home=home, token=token, reveal=reveal_fn, llm_for=llm_for
    )
    handler = type("StudioHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server
