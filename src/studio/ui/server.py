"""The Studio UI: a local chat app over the router, served with the Python standard library.

``studio ui`` starts a :class:`ThreadingHTTPServer` on 127.0.0.1 that serves the single-page app
in ``static/`` and a small JSON API. Message replies stream as Server-Sent Events: ``status``
(progress line), ``chunk`` (reply text), ``pending`` (an action waits for Approve/Reject) and
``done`` (files produced). Nothing is fetched from the internet; there is no telemetry.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from studio import __version__
from studio import digest as digestmod
from studio import session as sessmod
from studio.deck.writer import DECK_FILE
from studio.guards import scan_phi
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
MAX_UPLOAD = 200 * 1024 * 1024
MAX_JSON = 1024 * 1024
Send = Callable[[str, dict[str, Any]], None]


class ApiError(Exception):
    """An HTTP error with a user-facing message."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class StudioApp:
    """Everything the request handler needs; one per server."""

    root: Path
    llm_factory: Callable[[], LLMClient]
    router: Router = field(init=False)
    chats: ChatStore = field(init=False)
    _locks: dict[str, threading.Lock] = field(default_factory=dict, init=False)
    _locks_guard: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        self.router = Router(RouterContext(self.root, self.llm_factory, allow_local_paths=False))
        self.chats = ChatStore(self.root)

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
                    "created": opp.created,
                    "updated": chats[0].updated if chats else opp.created,
                    "chats": [c.summary() for c in chats],
                }
            )
        return sorted(out, key=lambda p: p["updated"], reverse=True)

    def project(self, project: str) -> dict[str, Any]:
        opp = self.opp(project)
        info = sessmod.opportunity_status(opp)
        input_dir = opp.path / "input"
        files = sorted(p.name for p in input_dir.glob("*") if p.is_file())
        return {
            "id": opp.id,
            "title": opp.title or opp.id,
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
                    async for piece in self.router.handle(step, attached, sess, emit):
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
            ("GET", r"/api/projects", "list_projects"),
            ("POST", r"/api/projects", "create_project"),
            ("GET", r"/api/projects/([^/]+)", "get_project"),
            ("PATCH", r"/api/projects/([^/]+)", "rename_project"),
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

    def _dispatch(self, method: str) -> None:
        path = urlparse(self.path).path
        try:
            if not self._local_request(method):
                raise ApiError(HTTPStatus.FORBIDDEN, "Only local requests are allowed.")
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
            self._json({"error": str(exc)}, exc.status)
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
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
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
        name = "index.html" if path in ("", "/") else path.lstrip("/")
        try:
            target = safe_name(STATIC, name)
        except StoreError as exc:
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
        self._json({"version": __version__, "ollama": ollama, "loaded": loaded or []})

    def api_list_projects(self) -> None:
        self._json(self.app.projects())

    def api_create_project(self) -> None:
        name = str(self._payload().get("name") or "").strip() or "Untitled project"
        opp = sessmod.create_project(self.app.root, name)
        chat = self.app.chats.create(opp.id)
        self._json({"project": self.app.project(opp.id), "chat": chat.model_dump()}, 201)

    def api_get_project(self, project: str) -> None:
        self._json(self.app.project(project))

    def api_rename_project(self, project: str) -> None:
        self.app.opp(project)
        sessmod.rename_opportunity(self.app.root, project, str(self._payload().get("title", "")))
        self._json(self.app.project(project))

    def api_create_chat(self, project: str) -> None:
        self.app.opp(project)
        self._json(self.app.chats.create(project).model_dump(), 201)

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
        chat.title = str(self._payload().get("title") or "").strip() or chat.title
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
    root: Path, llm_factory: Callable[[], LLMClient], port: int = 8765
) -> ThreadingHTTPServer:
    """A ready-to-serve UI server on 127.0.0.1:``port`` (0 picks a free port)."""
    app = StudioApp(root, llm_factory)
    handler = type("StudioHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server
