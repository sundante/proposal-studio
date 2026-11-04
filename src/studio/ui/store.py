"""Chats and staged uploads for the Studio UI.

A chat belongs to one project and is saved in the project's folder as ``chats/<chat-id>.json``.
Files dropped into the composer are staged in the project's ``.uploads/`` until the message that
carries them has been handled.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from studio import session as sessmod
from studio.guards import GuardError, resolve_in_sandbox

CHAT_ID = re.compile(r"^[0-9a-f]{12}$")
CHATS_DIR = "chats"
UPLOADS_DIR = ".uploads"
TITLE_CHARS = 60


class StoreError(ValueError):
    """Unknown chat or invalid file name. The message is user-facing."""


def now() -> str:
    """UTC timestamp for chat records."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class ChatMessage(BaseModel):
    """One turn in a chat."""

    role: Literal["user", "assistant"]
    content: str
    files: list[str] = Field(default_factory=list)  # names attached by the user
    outputs: list[str] = Field(default_factory=list)  # files produced (names in out/)
    sources: list[dict[str, Any]] = Field(default_factory=list)  # cited passages (file, page…)
    created: str = Field(default_factory=now)


class ChatPrefs(BaseModel):
    """Per-chat choices from the composer, remembered for the next message."""

    mode: Literal["auto", "ask", "research", "chat", "draft"] = "auto"
    model: str = ""  # worker model override ("" = the configured one)
    think: bool | None = None  # None = the configured default


class Chat(BaseModel):
    """A chat thread inside a project."""

    id: str
    project: str
    title: str = "New chat"
    created: str = Field(default_factory=now)
    updated: str = Field(default_factory=now)
    pinned: bool = False
    temporary: bool = False  # not listed or searched; deleted when left and at start-up
    prefs: ChatPrefs = Field(default_factory=ChatPrefs)
    messages: list[ChatMessage] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Sidebar entry (no messages)."""
        return {
            "id": self.id,
            "project": self.project,
            "title": self.title,
            "updated": self.updated,
            "pinned": self.pinned,
            "temporary": self.temporary,
            "has_files": any(m.files or m.outputs for m in self.messages),
        }

    def history(self, turns: int = 8) -> list[dict[str, str]]:
        """The last ``turns`` messages as ``{role, content}`` (for free chat)."""
        return [{"role": m.role, "content": m.content} for m in self.messages[-turns:]]


def title_from(text: str, files: list[str]) -> str:
    """A chat title from its first message (or its first file)."""
    words = " ".join(text.split())
    if words and not words.startswith("/"):
        return words if len(words) <= TITLE_CHARS else words[: TITLE_CHARS - 1].rstrip() + "…"
    if files:
        return Path(files[0]).stem.replace("_", " ").replace("-", " ")
    return words or "New chat"


class ChatStore:
    """Chats on disk under ``workspace/<project>/chats/``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, project: str) -> Path:
        return sessmod.get_opportunity(self.root, project).path / CHATS_DIR

    def _find(self, chat_id: str) -> Path:
        if not CHAT_ID.match(chat_id):
            raise StoreError(f"Unknown chat '{chat_id}'.")
        for opp in sessmod.list_opportunities(self.root):
            path = opp.path / CHATS_DIR / f"{chat_id}.json"
            if path.is_file():
                return path
        raise StoreError(f"Unknown chat '{chat_id}'.")

    def create(self, project: str, title: str = "New chat", *, temporary: bool = False) -> Chat:
        """A new, empty chat in ``project`` (``temporary`` chats are never listed)."""
        sessmod.get_opportunity(self.root, project)  # must exist
        chat = Chat(id=uuid.uuid4().hex[:12], project=project, title=title, temporary=temporary)
        self.save(chat)
        return chat

    def get(self, chat_id: str) -> Chat:
        """Load a chat by id."""
        return Chat.model_validate_json(self._find(chat_id).read_text(encoding="utf-8"))

    def save(self, chat: Chat) -> None:
        """Persist ``chat``."""
        folder = self._dir(chat.project)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{chat.id}.json").write_text(chat.model_dump_json(indent=2), encoding="utf-8")

    def delete(self, chat_id: str) -> None:
        """Remove a chat."""
        self._find(chat_id).unlink()

    def list(self, project: str, *, include_temporary: bool = False) -> list[Chat]:
        """Chats in ``project``, most recently updated first."""
        folder = self._dir(project)
        if not folder.exists():
            return []
        chats = [
            Chat.model_validate_json(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")
        ]
        chats = [c for c in chats if include_temporary or not c.temporary]
        return sorted(chats, key=lambda c: c.updated, reverse=True)

    def purge_temporary(self, keep: str | None = None) -> int:
        """Delete temporary chats (except ``keep``); returns how many were removed."""
        removed = 0
        for opp in sessmod.list_opportunities(self.root):
            for chat in self.list(opp.id, include_temporary=True):
                if chat.temporary and chat.id != keep:
                    (self._dir(opp.id) / f"{chat.id}.json").unlink(missing_ok=True)
                    removed += 1
        return removed

    def search(self, query: str, limit: int = 30) -> list[dict[str, Any]]:
        """Chats whose title or messages contain ``query`` (case-insensitive), with a snippet."""
        q = query.strip().lower()
        if not q:
            return []
        hits = []
        for opp in sessmod.list_opportunities(self.root):
            for chat in self.list(opp.id):
                snippet = ""
                if q not in chat.title.lower():
                    text = next((m.content for m in chat.messages if q in m.content.lower()), "")
                    if not text:
                        continue
                    snippet = _snippet(text, q)
                hits.append({**chat.summary(), "snippet": snippet, "project_title": opp.title})
        hits.sort(key=lambda c: c["updated"], reverse=True)
        return hits[:limit]

    def recent(self, limit: int = 30) -> list[Chat]:
        """Chats across all projects, most recently updated first."""
        chats = [
            chat
            for opp in sessmod.list_opportunities(self.root)
            for chat in self.list(opp.id)
            if chat.messages
        ]
        return sorted(chats, key=lambda c: c.updated, reverse=True)[:limit]


def _snippet(text: str, q: str, width: int = 120) -> str:
    """About ``width`` characters around the first match, on one line."""
    flat = " ".join(text.split())
    i = flat.lower().find(q)
    start = max(0, i - width // 3)
    piece = flat[start : start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(flat) else "")


def uploads_dir(opp: sessmod.Opportunity) -> Path:
    """Staging folder for files dropped into a project's chats."""
    return opp.path / UPLOADS_DIR


def safe_name(folder: Path, name: str) -> Path:
    """``folder/name`` for a plain file name; rejects paths, hidden names and traversal."""
    plain = Path(name).name
    if not plain or plain != name or plain.startswith("."):
        raise StoreError(f"Invalid file name '{name}'.")
    try:
        return resolve_in_sandbox(folder, plain)
    except GuardError as exc:
        raise StoreError(str(exc)) from exc
