"""Opportunities (projects) and per-chat session state.

Two layouts share this module:

- **CLI** (``studio new`` …): opportunities live in ``<root>/workspace/<opp-id>/``.
- **App** (``studio ui``): ``root`` is the *Proposal Studio folder* (default
  ``~/Documents/Proposal Studio``), marked by ``.studio/home.json``. It holds the shared
  ``library/``; each **project** lives in a folder the user chose and trusted (anywhere), listed in
  ``.studio/projects.json`` as ``{id: path}``.

Sessions are keyed by chat id (``ui-<chat>`` in the app; the CLI uses ``cli``) and persisted
as JSON under ``workspace/.sessions/`` (CLI) or ``.studio/.sessions/`` (app).
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from studio import digest as digestmod
from studio.rag import VectorIndex

OPP_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
OPP_SUBDIRS = ("input", "index", "research", "agent", "out")
OPP_FILE = "opportunity.json"


class SessionError(ValueError):
    """Invalid opportunity or session operation. The message is user-facing."""


class Opportunity(BaseModel):
    """One proposal opportunity (a project in the app) and its folder."""

    id: str
    title: str = ""
    created: str = ""
    path: Path = Field(exclude=True)


class Session(BaseModel):
    """Per-chat state."""

    key: str
    active_opp: str | None = None
    last_outputs: dict[str, Any] = Field(default_factory=dict)


MARKER_DIR = ".studio"  # in the Proposal Studio folder: project list, sessions, caches
HOME_MARKER = "home.json"
REGISTRY_FILE = "projects.json"
LIBRARY_DIR = "library"
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def is_studio_home(root: Path) -> bool:
    """True for the app's Proposal Studio folder (projects are then listed in a registry)."""
    return (root / MARKER_DIR / HOME_MARKER).is_file()


def init_home(root: Path) -> Path:
    """Create the Proposal Studio folder with its ``library/`` and ``.studio/`` marker."""
    (root / MARKER_DIR).mkdir(parents=True, exist_ok=True)
    (root / LIBRARY_DIR).mkdir(exist_ok=True)
    marker = root / MARKER_DIR / HOME_MARKER
    if not marker.exists():
        marker.write_text(json.dumps({"created": _now(), "app": "proposal-studio"}, indent=2))
    return root


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def workspace_dir(root: Path) -> Path:
    """Internal state: ``.studio/`` in the app; ``workspace/`` (with the projects) in the CLI."""
    return root / (MARKER_DIR if is_studio_home(root) else "workspace")


def _registry(root: Path) -> dict[str, str]:
    path = root / MARKER_DIR / REGISTRY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str) and OPP_ID.match(k)}


def _write_registry(root: Path, registry: dict[str, str]) -> None:
    path = root / MARKER_DIR / REGISTRY_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(registry.items())), indent=2), encoding="utf-8")
    tmp.replace(path)


def registry_entries(root: Path) -> list[tuple[str, Path, bool]]:
    """App projects as ``(id, folder, still there?)`` — includes folders moved or deleted."""
    return [(k, Path(v), (Path(v) / OPP_FILE).is_file()) for k, v in _registry(root).items()]


def project_path(root: Path, opp_id: str) -> Path:
    """The folder of opportunity ``opp_id`` (it may not exist)."""
    validate_opp_id(opp_id)
    if is_studio_home(root):
        known = _registry(root).get(opp_id)
        if known is None:
            raise SessionError(f"No project '{opp_id}'.")
        return Path(known)
    return workspace_dir(root) / opp_id


def folder_name(name: str) -> str:
    """A safe folder name from a display name, spaces kept: ``"Acme: RFP"`` → ``Acme- RFP``."""
    cleaned = _BAD_CHARS.sub("-", name).strip(" .-")[:80].strip(" .")
    return cleaned or "Project"


def default_project_folder(root: Path, name: str) -> Path:
    """A new folder for ``name`` in the Proposal Studio folder (``Name``, ``Name 2`` …)."""
    base = folder_name(name)
    candidate, n = root / base, 2
    while candidate.exists() or candidate.name.lower() == LIBRARY_DIR:
        candidate, n = root / f"{base} {n}", n + 1
    return candidate


def _check_project_folder(root: Path, path: Path) -> None:
    """Refuse the Proposal Studio folder itself, its library/internals, or nesting in a project."""
    path, home = path.resolve(), root.resolve()
    special = {home, home / LIBRARY_DIR, home / MARKER_DIR}
    if path in special or any(s in path.parents for s in special - {home}):
        raise SessionError(f"{path} is Proposal Studio's own folder. Choose another folder.")
    for other_id, other, _ in registry_entries(root):
        other = other.resolve()
        if path == other:
            raise SessionError(f"{path} is already the project '{other_id}'.")
        if other in path.parents or path in other.parents:
            raise SessionError(
                f"{path} overlaps the project folder {other}. Choose another folder."
            )


def validate_opp_id(opp_id: str) -> str:
    """Return ``opp_id`` if it is a valid slug, else raise :class:`SessionError`."""
    if not OPP_ID.match(opp_id):
        raise SessionError(
            f"'{opp_id}' isn't a valid opportunity id. Use lowercase letters, digits and dashes "
            "(e.g. acme-2026-ai)."
        )
    return opp_id


def create_opportunity(
    root: Path, opp_id: str, title: str = "", folder: Path | None = None
) -> Opportunity:
    """Create an opportunity with its subfolders. Errors if it already exists.

    In the app, ``folder`` is where the project lives (default: a new folder named after the
    title inside the Proposal Studio folder) and the project is added to the registry.
    """
    validate_opp_id(opp_id)
    home = is_studio_home(root)
    if home:
        if opp_id in _registry(root):
            raise SessionError(f"A project with id '{opp_id}' already exists.")
        path = (folder or default_project_folder(root, title or opp_id)).resolve()
        if (path / OPP_FILE).exists():
            raise SessionError(f"{path} already holds a project. Open it instead.")
        _check_project_folder(root, path)
    else:
        path = workspace_dir(root) / opp_id
        if (path / OPP_FILE).exists():
            raise SessionError(f"Opportunity '{opp_id}' already exists. Use `/use {opp_id}`.")
    for sub in OPP_SUBDIRS:
        (path / sub).mkdir(parents=True, exist_ok=True)
    opp = Opportunity(id=opp_id, title=title, created=_now(), path=path)
    (path / OPP_FILE).write_text(opp.model_dump_json(indent=2), encoding="utf-8")
    if home:
        registry = _registry(root)
        registry[opp_id] = str(path)
        _write_registry(root, registry)
    return opp


def slugify(name: str) -> str:
    """A valid opportunity id from free text: ``"Acme RFP (2026)"`` → ``acme-rfp-2026``."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50].strip("-")
    return slug or "project"


def _unique_id(root: Path, name: str) -> str:
    taken = set(_registry(root)) if is_studio_home(root) else set()
    base = slugify(name)
    slug, n = base, 2
    while slug in taken or (not is_studio_home(root) and (workspace_dir(root) / slug).exists()):
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_project(root: Path, name: str, folder: Path | None = None) -> Opportunity:
    """Create an opportunity from a display name; its id is a unique slug (``-2``, ``-3``…)."""
    return create_opportunity(root, _unique_id(root, name), name.strip() or "Project", folder)


def import_project(root: Path, folder: Path) -> Opportunity:
    """Add an existing project folder (one with ``opportunity.json``) to the app's list."""
    path = folder.resolve()
    meta = path / OPP_FILE
    if not meta.is_file():
        raise SessionError(f"{path} isn't a Proposal Studio project folder.")
    _check_project_folder(root, path)
    data = json.loads(meta.read_text(encoding="utf-8"))
    opp = Opportunity(**data, path=path)
    if opp.id in _registry(root):
        opp.id = _unique_id(root, opp.title or opp.id)
        meta.write_text(opp.model_dump_json(indent=2), encoding="utf-8")
    registry = _registry(root)
    registry[opp.id] = str(path)
    _write_registry(root, registry)
    return opp


def remove_project(root: Path, opp_id: str, *, delete_files: bool = False) -> Path:
    """Remove a project from the app; with ``delete_files``, also delete its folder.

    Deleting only ever removes a folder that contains this project's ``opportunity.json``.
    """
    path = project_path(root, opp_id)
    if delete_files and path.exists():
        meta = path / OPP_FILE
        try:
            owner = json.loads(meta.read_text(encoding="utf-8")).get("id")
        except (OSError, ValueError):
            owner = None
        if owner != opp_id:
            raise SessionError(f"{path} doesn't look like this project's folder; not deleting it.")
        _guard_delete(root, path)
        shutil.rmtree(path)
    if is_studio_home(root):
        registry = _registry(root)
        registry.pop(opp_id, None)
        _write_registry(root, registry)
    return path


def _guard_delete(root: Path, path: Path) -> None:
    resolved = path.resolve()
    forbidden = {root.resolve(), Path.home().resolve(), (root / LIBRARY_DIR).resolve()}
    if resolved in forbidden or resolved.parent == resolved:
        raise SessionError(f"Refusing to delete {resolved}.")


def rename_opportunity(root: Path, opp_id: str, title: str) -> Opportunity:
    """Change an opportunity's display title (the folder keeps its name)."""
    opp = get_opportunity(root, opp_id)
    opp.title = title.strip() or opp.id
    (opp.path / OPP_FILE).write_text(opp.model_dump_json(indent=2), encoding="utf-8")
    return opp


def get_opportunity(root: Path, opp_id: str) -> Opportunity:
    """Load an existing opportunity."""
    path = project_path(root, opp_id)
    meta = path / OPP_FILE
    if not meta.exists():
        if is_studio_home(root):
            raise SessionError(f"The folder of project '{opp_id}' is missing: {path}")
        raise SessionError(f"No opportunity '{opp_id}'. Create it with `/new {opp_id}`.")
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["id"] = opp_id
    return Opportunity(**data, path=path)


def list_opportunities(root: Path) -> list[Opportunity]:
    """All opportunities whose folder is present, sorted by id."""
    if is_studio_home(root):
        return [get_opportunity(root, k) for k, _, ok in sorted(registry_entries(root)) if ok]
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
        "digest": (opp.path / digestmod.DIGEST_FILE).exists(),
        "digest_stale": digestmod.is_stale(opp.path),
        "outline": (opp.path / "outline.json").exists(),
        "deck": (opp.path / "deck.json").exists(),
        "renders": sorted(p.name for p in out.glob("*.pptx")) if out.exists() else [],
    }
