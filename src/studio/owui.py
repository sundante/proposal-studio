"""Open WebUI bridge: what the ``owui/*.py`` function files do, in a testable module.

The function files pasted into Open WebUI stay tiny and delegate here. Open WebUI internals
(file storage, file records) are imported lazily, only inside Open WebUI; tests inject fakes.
Facts this relies on were verified against open-webui 0.13.0 (see vibes/DECISIONS.md).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import mimetypes
import os
import shutil
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from studio import config as cfgmod
from studio.guards import scan_phi
from studio.llm import LLMClient, OllamaClient
from studio.router import Router, RouterContext

Emit = Callable[[dict[str, Any]], Any]
Resolver = Callable[[str], Awaitable[str | None]]  # file id -> local path
Publisher = Callable[[Path, str], Awaitable[str | None]]  # (file, user id) -> download url


# --- message text ---------------------------------------------------------------------------


def message_text(message: dict[str, Any]) -> str:
    """Text of a chat message whose content is a string or a list of parts."""
    content = message.get("content", "")
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if p.get("type") == "text")
    return str(content or "")


def extract_user_text(body: dict[str, Any]) -> str:
    """The user's latest message, without any RAG context Open WebUI prepended to it.

    With ``RAG_SYSTEM_CONTEXT=False`` Open WebUI prefixes the message with its RAG template,
    which ends in ``</context>``; the user's own text follows it.
    """
    for message in reversed(body.get("messages") or []):
        if message.get("role") == "user":
            text = message_text(message)
            if "</context>" in text:
                text = text.rsplit("</context>", 1)[1]
            return text.strip()
    return ""


def session_key(chat_id: str | None, user: dict[str, Any] | None) -> str:
    """Router session per Open WebUI chat (fallback: per user)."""
    if chat_id:
        return f"owui-chat-{chat_id}"
    return f"owui-user-{(user or {}).get('id', 'anonymous')}"


def phi_warning(body: dict[str, Any]) -> str | None:
    """A one-line warning if the latest user message looks like it contains PHI."""
    hits = scan_phi(extract_user_text(body))
    if not hits:
        return None
    kinds = ", ".join(sorted({h.kind for h in hits}))
    return f"⚠ Possible PHI in your message ({kinds}). RFP work should not include patient data."


# --- files ----------------------------------------------------------------------------------


async def owui_resolver(file_id: str) -> str | None:
    """Local path of an Open WebUI file (inside Open WebUI only)."""
    try:
        from open_webui.models.files import Files
        from open_webui.storage.provider import Storage
    except ImportError:
        return None
    record = await Files.get_file_by_id(file_id)
    if record is None or not record.path:
        return None
    return await asyncio.to_thread(Storage.get_file, record.path)


async def owui_publisher(path: Path, user_id: str) -> str | None:
    """Store ``path`` as an Open WebUI file owned by ``user_id``; return its download URL."""
    try:
        from open_webui.models.files import FileForm, Files
        from open_webui.storage.provider import Storage
    except ImportError:
        return None
    file_id = str(uuid.uuid4())
    tags = {"OpenWebUI-User-Id": user_id, "OpenWebUI-File-Id": file_id}
    with path.open("rb") as handle:
        _contents, stored = await asyncio.to_thread(
            Storage.upload_file, handle, f"{file_id}_{path.name}", tags
        )
    meta = {
        "name": path.name,
        "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "size": path.stat().st_size,
    }
    form = FileForm(id=file_id, filename=path.name, path=stored, data={}, meta=meta)
    await Files.insert_new_file(user_id, form)
    return f"/api/v1/files/{file_id}/content"


async def materialize_files(
    items: Sequence[dict[str, Any]], dest: Path, resolver: Resolver = owui_resolver
) -> tuple[list[Path], list[str]]:
    """Copy attached files into ``dest`` under their original names; return (paths, notes)."""
    paths, notes = [], []
    for item in items:
        if item.get("type") not in (None, "file", "doc"):
            notes.append(f"Skipped attachment of type '{item.get('type')}' (only files are used).")
            continue
        info = item.get("file") or {}
        name = Path(
            info.get("filename") or item.get("name") or (info.get("meta") or {}).get("name") or ""
        ).name
        file_id = item.get("id") or info.get("id")
        source = info.get("path")
        if file_id and not (source and Path(source).exists()):
            source = await resolver(file_id)
        if not source or not Path(source).exists() or not name:
            notes.append(f"Couldn't read attachment {name or file_id or '?'}.")
            continue
        target = dest / name
        shutil.copy2(source, target)
        paths.append(target)
    return paths, notes


# --- the pipe -------------------------------------------------------------------------------


def resolve_root(valve_value: str = "") -> Path:
    """Project folder: the STUDIO_HOME valve, else ``$STUDIO_HOME``, else the current folder."""
    return Path(valve_value or os.environ.get("STUDIO_HOME") or Path.cwd()).expanduser().resolve()


async def _call(fn: Callable[..., Any] | None, event: dict[str, Any]) -> Any:
    if fn is None:
        return None
    result = fn(event)
    return await result if inspect.isawaitable(result) else result


class PipeBridge:
    """Runs one Open WebUI message through the router, adding attachments and downloads."""

    def __init__(
        self,
        root: Path,
        *,
        llm_factory: Callable[[], LLMClient] | None = None,
        route_overrides: dict[str, Any] | None = None,
        resolver: Resolver = owui_resolver,
        publisher: Publisher = owui_publisher,
    ) -> None:
        self.root = root
        factory = llm_factory or (lambda: OllamaClient(cfgmod.load_config(root).models))
        self.router = Router(RouterContext(root, factory, False, dict(route_overrides or {})))
        self.resolver = resolver
        self.publisher = publisher

    async def run(
        self,
        body: dict[str, Any],
        *,
        user: dict[str, Any] | None = None,
        chat_id: str | None = None,
        files: Sequence[dict[str, Any]] = (),
        emit: Emit | None = None,
        event_call: Emit | None = None,
        task: str | None = None,
        default_opportunity: str = "",
        agent: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream the reply for the latest user message.

        With ``agent`` (the "Agent · …" models), plain text becomes ``/agent <agent> <text>``;
        `/commands` such as `/approve` still work as typed.
        """
        if task:  # title/tag/follow-up generation: not ours to answer
            return
        if not (self.root / "config").is_dir():
            yield (
                f"⚠ Proposal Studio can't find its project folder ({self.root}). Set the "
                "`STUDIO_HOME` valve (Admin → Functions → Proposal Studio → Valves)."
            )
            return
        user = user or {}
        sess = self.router.session(session_key(chat_id, user))
        if not sess.active_opp and default_opportunity:
            sess.active_opp = default_opportunity
        sess.last_outputs.pop("produced", None)
        text = extract_user_text(body)
        if agent and text and not text.startswith("/"):
            text = f"/agent {agent} {text}"

        with tempfile.TemporaryDirectory(prefix="studio-owui-") as tmp:
            attachments, notes = await materialize_files(files, Path(tmp), self.resolver)
            for note in notes:
                yield f"_{note}_\n\n"
            had_pending = "pending" in sess.last_outputs
            async for chunk in self.router.handle(text, attachments, sess, emit):
                yield chunk
            pending = sess.last_outputs.get("pending")
            if pending and not had_pending and event_call is not None:
                answer = await _call(
                    event_call,
                    {
                        "type": "confirmation",
                        "data": {
                            "title": "Proposal Studio",
                            "message": f"Run `/{pending['command']}` now? It writes files.",
                        },
                    },
                )
                yield "\n\n"
                if answer is True or answer is False:
                    # Only an explicit yes/no from the dialog counts. Open WebUI returns an
                    # error dict when no browser is connected; that must never approve.
                    async for chunk in self.router.handle(
                        "/approve" if answer else "/reject", [], sess, emit
                    ):
                        yield chunk
                else:
                    yield "_No answer from the confirmation dialog; type `/approve` or `/reject`._"

        produced = sess.last_outputs.pop("produced", [])
        self.router.store.save(sess)
        for item in produced:  # offer new files (PPTX, XLSX, reports) for download
            path = Path(item)
            url = await self.publisher(path, user.get("id", "")) if path.exists() else None
            if url:
                yield f"\n\n📎 [Download {path.name}]({url})"


# --- prompts and automated install ----------------------------------------------------------

FUNCTIONS = (  # (function id, file in owui/, display name)
    ("proposal_studio", "router_pipe.py", "Proposal Studio"),
    ("proposal_studio_agents", "agents_pipe.py", "Proposal Studio Agents"),
    ("proposal_studio_phi", "phi_filter.py", "Proposal Studio PHI warning"),
)
SKIP_PROMPTS = {"approve", "reject"}  # typed rarely; the confirmation dialog covers them


def agent_models(root: Path) -> list[dict[str, str]]:
    """Manifold entries: one "Agent · <label>" model per enabled agent in agents.yaml."""
    try:
        agents = cfgmod.load_config(root).agents.agents
    except cfgmod.ConfigError:
        return []
    return [
        {"id": name, "name": f"Agent · {spec.label}"}
        for name, spec in agents.items()
        if spec.enabled
    ]


def agent_from_model(model_id: str) -> str:
    """``proposal_studio_agents.opencode`` → ``opencode``."""
    return model_id.split(".", 1)[1] if "." in model_id else model_id


def prompt_entries(routes: cfgmod.RoutesConfig) -> list[dict[str, str]]:
    """One Open WebUI Prompt per command: typing `/` lists them; choosing inserts `/cmd `."""
    return [
        {"command": name, "name": f"/{name} — {spec.help}", "content": f"/{name} "}
        for name, spec in routes.commands.items()
        if name not in SKIP_PROMPTS
    ]


def write_prompts(routes: cfgmod.RoutesConfig, out_dir: Path) -> list[Path]:
    """Write ``<command>.json`` per prompt plus ``all.json`` (for Workspace → Prompts → Import)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = prompt_entries(routes)
    written = []
    for entry in entries:
        path = out_dir / f"{entry['command']}.json"
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    (out_dir / "all.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return [*written, out_dir / "all.json"]


class InstallError(ValueError):
    """Automated Open WebUI install failed. User-facing."""


def install(
    base_url: str,
    token: str,
    root: Path,
    *,
    global_filter: bool = False,
    transport: Any = None,
    log: Callable[[str], None] = print,
) -> None:
    """Create/update our functions and prompts in a local Open WebUI through its API."""
    host = urlparse(base_url).hostname or ""
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise InstallError(
            f"Refusing to install into {base_url}: only a local Open WebUI is allowed."
        )
    client = httpx.Client(
        base_url=base_url.rstrip("/") + "/api/v1",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
        transport=transport,
    )

    def check(resp: httpx.Response, what: str) -> httpx.Response:
        if resp.status_code in (401, 403):
            raise InstallError(
                f"{what}: not authorised. Use an admin API key (Settings → Account)."
            )
        if resp.status_code >= 400:
            raise InstallError(f"{what}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp

    owui_dir = root / "owui"
    for function_id, filename, name in FUNCTIONS:
        content = (owui_dir / filename).read_text(encoding="utf-8")
        form = {"id": function_id, "name": name, "content": content, "meta": {"description": name}}
        existing = client.get(f"/functions/id/{function_id}")
        if existing.status_code == 200:
            check(client.post(f"/functions/id/{function_id}/update", json=form), f"update {name}")
            current = existing.json()
            log(f"Updated function {name}")
        else:
            current = check(client.post("/functions/create", json=form), f"create {name}").json()
            log(f"Created function {name}")
        if not current.get("is_active"):
            check(client.post(f"/functions/id/{function_id}/toggle"), f"enable {name}")
        if function_id.endswith("_phi") and global_filter and not current.get("is_global"):
            check(client.post(f"/functions/id/{function_id}/toggle/global"), f"globalise {name}")

    routes = cfgmod.load_config(root).routes
    for entry in prompt_entries(routes):
        resp = client.post("/prompts/create", json=entry)
        error_text = resp.text.lower()
        if resp.status_code == 400 and (
            "already registered" in error_text or "command taken" in error_text
        ):
            log(f"Prompt /{entry['command']} already exists (kept)")
            continue
        check(resp, f"prompt /{entry['command']}")
        log(f"Created prompt /{entry['command']}")
