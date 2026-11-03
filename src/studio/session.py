"""Opportunities (``workspace/<opp-id>/``) and per-chat session state.

Sessions are keyed by Open WebUI chat id (fallback: user id; the CLI uses ``cli``) and persisted
as JSON under ``workspace/.sessions/`` so they survive restarts.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from studio.rag import VectorIndex

OPP_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
OPP_SUBDIRS = ("input", "index", "research", "agent", "out")
OPP_FILE = "opportunity.json"


class SessionError(ValueError):
    """Invalid opportunity or session operation. The message is user-facing."""


class Opportunity(BaseModel):
    """One proposal opportunity and its workspace folder."""

    id: str
    title: str = ""
    created: str = ""
    path: Path = Field(exclude=True)


class Session(BaseModel):
    """Per-chat state."""

    key: str
    active_opp: str | None = None
    last_outputs: dict[str, Any] = Field(default_factory=dict)


def workspace_dir(root: Path) -> Path:
    """The ``workspace/`` folder under the project root."""
    return root / "workspace"


def validate_opp_id(opp_id: str) -> str:
    """Return ``opp_id`` if it is a valid slug, else raise :class:`SessionError`."""
    if not OPP_ID.match(opp_id):
        raise SessionError(
            f"'{opp_id}' isn't a valid opportunity id. Use lowercase letters, digits and dashes "
            "(e.g. acme-2026-ai)."
        )
    return opp_id


def create_opportunity(root: Path, opp_id: str, title: str = "") -> Opportunity:
    """Create ``workspace/<opp_id>/`` with its subfolders. Errors if it already exists."""
    path = workspace_dir(root) / validate_opp_id(opp_id)
    if (path / OPP_FILE).exists():
        raise SessionError(f"Opportunity '{opp_id}' already exists. Use `/use {opp_id}`.")
    for sub in OPP_SUBDIRS:
        (path / sub).mkdir(parents=True, exist_ok=True)
    opp = Opportunity(
        id=opp_id, title=title, created=datetime.now(UTC).isoformat(timespec="seconds"), path=path
    )
    (path / OPP_FILE).write_text(opp.model_dump_json(indent=2), encoding="utf-8")
    return opp


def get_opportunity(root: Path, opp_id: str) -> Opportunity:
    """Load an existing opportunity."""
    path = workspace_dir(root) / validate_opp_id(opp_id)
    meta = path / OPP_FILE
    if not meta.exists():
        raise SessionError(f"No opportunity '{opp_id}'. Create it with `/new {opp_id}`.")
    data = json.loads(meta.read_text(encoding="utf-8"))
    return Opportunity(**data, path=path)


def list_opportunities(root: Path) -> list[Opportunity]:
    """All opportunities, sorted by id."""
    base = workspace_dir(root)
    if not base.exists():
        return []
    return [
        get_opportunity(root, p.name)
        for p in sorted(base.iterdir())
        if p.is_dir() and (p / OPP_FILE).exists() and OPP_ID.match(p.name)
    ]


class SessionStore:
    """Load and save :class:`Session` objects under ``workspace/.sessions/``."""

    def __init__(self, root: Path) -> None:
        self.dir = workspace_dir(root) / ".sessions"

    def _path(self, key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:128] or "default"
        return self.dir / f"{safe}.json"

    def load(self, key: str) -> Session:
        """The session for ``key`` (a fresh one if none is stored)."""
        path = self._path(key)
        if path.exists():
            return Session.model_validate_json(path.read_text(encoding="utf-8"))
        return Session(key=key)

    def save(self, session: Session) -> None:
        """Persist ``session``."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(session.key).write_text(session.model_dump_json(indent=2), encoding="utf-8")


def active_opportunity(root: Path, session: Session, override: str | None = None) -> Opportunity:
    """The opportunity to act on: ``override`` if given, else the session's active one."""
    opp_id = override or session.active_opp
    if not opp_id:
        raise SessionError("No active opportunity. Create one with `/new <opp-id>` or `/use`.")
    return get_opportunity(root, opp_id)


def opportunity_status(opp: Opportunity) -> dict[str, Any]:
    """Pipeline status for an opportunity: ingested files, chunks, digest/deck/render."""
    index = VectorIndex(opp.path / "index")
    out = opp.path / "out"
    return {
        "id": opp.id,
        "title": opp.title,
        "files": {name: index.file_chunk_count(name) for name in index.files()},
        "chunks": len(index),
        "digest": (opp.path / "digest.json").exists(),
        "outline": (opp.path / "outline.json").exists(),
        "deck": (opp.path / "deck.json").exists(),
        "renders": sorted(p.name for p in out.glob("*.pptx")) if out.exists() else [],
    }
