"""Trusted workspace folders for ``studio ui`` (like an editor's "Do you trust this folder?").

The UI only reads and writes inside a folder the user has explicitly trusted. Trust is recorded
per user, outside any workspace, in ``trusted.json`` under :func:`user_dir`
(``%APPDATA%\\ProposalStudio`` on Windows, ``~/.proposal-studio`` elsewhere; ``$STUDIO_USER_DIR``
overrides it). A trusted folder gets a ``.studio/workspace.json`` marker; projects then live in
``projects/`` and the library in ``library/``.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from studio.session import MARKER_DIR, MARKER_FILE

REGISTRY = "trusted.json"
# Folders that must never become a workspace (the user's whole disk or system areas).
SYSTEM_DIRS_POSIX = (
    "/bin", "/boot", "/dev", "/etc", "/lib", "/opt", "/proc", "/sbin", "/sys", "/usr", "/var",
    "/System", "/Library", "/Applications", "/private", "/Volumes", "/media", "/mnt", "/tmp",
)  # fmt: skip
SYSTEM_DIRS_WINDOWS = ("Windows", "Program Files", "Program Files (x86)", "ProgramData")


class TrustError(ValueError):
    """A folder that can't be used as a workspace. User-facing."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def user_dir() -> Path:
    """Per-user settings folder (not inside any workspace)."""
    override = os.environ.get("STUDIO_USER_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "ProposalStudio"
    return Path.home() / ".proposal-studio"


def _load() -> dict[str, Any]:
    path = user_dir() / REGISTRY
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("workspaces", [])
    data.setdefault("open_last", False)
    return data


def _save(data: dict[str, Any]) -> None:
    folder = user_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{REGISTRY}.tmp"
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(folder / REGISTRY)


def check_candidate(path: str | Path) -> Path:
    """The absolute folder for ``path``, or :class:`TrustError` if it's unsafe as a workspace."""
    raw = str(path).strip()
    if not raw:
        raise TrustError("Choose a folder.")
    folder = Path(raw).expanduser()
    if not folder.is_absolute():
        raise TrustError("Use a full folder path, e.g. C:\\Bids\\Acme or ~/Bids/Acme.")
    folder = folder.resolve()
    if folder.exists() and not folder.is_dir():
        raise TrustError(f"{folder} is a file, not a folder.")
    if folder.parent == folder:
        raise TrustError("A whole drive can't be a workspace. Pick or create a folder in it.")
    if folder == Path.home().resolve():
        raise TrustError("Your home folder is too broad. Pick or create a folder inside it.")
    if folder == user_dir().resolve() or user_dir().resolve() in folder.parents:
        raise TrustError("That folder holds Proposal Studio's own settings.")
    if sys.platform == "win32":
        if len(folder.parts) >= 2 and folder.parts[1] in SYSTEM_DIRS_WINDOWS:
            raise TrustError(f"{folder} is a system folder.")
    elif not _user_area(folder):
        text = folder.as_posix()
        for system in SYSTEM_DIRS_POSIX:
            if text == system or text.startswith(system + "/"):
                raise TrustError(f"{folder} is a system folder.")
    return folder


def _user_area(folder: Path) -> bool:
    """Inside the home folder, the temp folder, or on an external drive (POSIX)."""
    areas = [Path.home(), Path(tempfile.gettempdir()), Path("/tmp")]
    for area in areas:
        resolved = area.resolve()
        if resolved in folder.parents:
            return True
    parts = folder.parts  # ("/", "Volumes", "Drive", "Bids", …)
    return len(parts) >= 4 and parts[1] in ("Volumes", "media", "mnt")


def trusted() -> list[dict[str, str]]:
    """Trusted workspaces, most recently used first (only folders that still exist)."""
    items = [w for w in _load()["workspaces"] if Path(w["path"]).is_dir()]
    return sorted(items, key=lambda w: w.get("last_used", ""), reverse=True)


def is_trusted(path: str | Path) -> bool:
    """True if ``path`` was trusted and still has its marker."""
    folder = Path(path).expanduser().resolve()
    known = any(Path(w["path"]) == folder for w in _load()["workspaces"])
    return known and (folder / MARKER_DIR / MARKER_FILE).is_file()


def trust(path: str | Path) -> Path:
    """Create (if needed) and trust a workspace folder; returns its absolute path."""
    folder = check_candidate(path)
    marker = folder / MARKER_DIR / MARKER_FILE
    marker.parent.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps({"created": _now(), "app": "proposal-studio"}, indent=2))
    for sub in ("projects", "library"):
        (folder / sub).mkdir(exist_ok=True)
    data = _load()
    data["workspaces"] = [w for w in data["workspaces"] if Path(w["path"]) != folder]
    data["workspaces"].append({"path": str(folder), "trusted_at": _now(), "last_used": _now()})
    _save(data)
    return folder


def untrust(path: str | Path) -> None:
    """Forget a workspace (its files are left alone)."""
    folder = Path(path).expanduser().resolve()
    data = _load()
    data["workspaces"] = [w for w in data["workspaces"] if Path(w["path"]) != folder]
    _save(data)


def touch(path: str | Path) -> None:
    """Record that a trusted workspace was opened now."""
    folder = Path(path).expanduser().resolve()
    data = _load()
    for w in data["workspaces"]:
        if Path(w["path"]) == folder:
            w["last_used"] = _now()
    _save(data)


def open_last() -> bool:
    """Whether to open the last workspace at launch without asking."""
    return bool(_load()["open_last"])


def set_open_last(value: bool) -> None:
    """Remember the "open my last workspace" choice."""
    data = _load()
    data["open_last"] = bool(value)
    _save(data)


def last_workspace() -> Path | None:
    """The most recently used trusted workspace, if any."""
    for w in trusted():
        if is_trusted(w["path"]):
            return Path(w["path"])
    return None
