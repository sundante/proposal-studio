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
from typing import Literal

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
    created: str = Field(default_factory=now)


class Chat(BaseModel):
    """A chat thread inside a project."""

    id: str
    project: str
    title: str = "New chat"
    created: str = Field(default_factory=now)
    updated: str = Field(default_factory=now)
    messages: list[ChatMessage] = Field(default_factory=list)

    def summary(self) -> dict[str, str]:
        """Sidebar entry (no messages)."""
        return {
            "id": self.id,
            "project": self.project,
            "title": self.title,
            "updated": self.updated,
        }


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

    def create(self, project: str, title: str = "New chat") -> Chat:
        """A new, empty chat in ``project``."""
        sessmod.get_opportunity(self.root, project)  # must exist
        chat = Chat(id=uuid.uuid4().hex[:12], project=project, title=title)
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

    def list(self, project: str) -> list[Chat]:
        """Chats in ``project``, most recently updated first."""
        folder = self._dir(project)
        if not folder.exists():
            return []
        chats = [
            Chat.model_validate_json(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")
        ]
        return sorted(chats, key=lambda c: c.updated, reverse=True)

    def recent(self, limit: int = 30) -> list[Chat]:
        """Chats across all projects, most recently updated first."""
        chats = [
            chat
            for opp in sessmod.list_opportunities(self.root)
            for chat in self.list(opp.id)
            if chat.messages
        ]
        return sorted(chats, key=lambda c: c.updated, reverse=True)[:limit]


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
