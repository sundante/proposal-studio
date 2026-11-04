"""Folder safety and per-user settings for ``studio ui``.

Every project lives in a folder the user picked and explicitly trusted. :func:`check_candidate`
refuses folders that are unsafe to read and write (whole drives, the home folder itself, system
folders, the app's own settings). Per-user settings live outside any project in
:func:`user_dir` (``%APPDATA%\\ProposalStudio`` on Windows, ``~/.proposal-studio`` elsewhere;
``$STUDIO_USER_DIR`` overrides it): currently just where the *Proposal Studio folder* is (the
shared ``library/`` and the default place for new projects).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

SETTINGS = "settings.json"
APP_FOLDER = "Proposal Studio"
SYSTEM_DIRS_POSIX = (
    "/bin", "/boot", "/dev", "/etc", "/lib", "/opt", "/proc", "/sbin", "/sys", "/usr", "/var",
    "/System", "/Library", "/Applications", "/private", "/Volumes", "/media", "/mnt", "/tmp",
)  # fmt: skip
SYSTEM_DIRS_WINDOWS = ("Windows", "Program Files", "Program Files (x86)", "ProgramData")


class TrustError(ValueError):
    """A folder that can't be used. User-facing."""


def user_dir() -> Path:
    """Per-user settings folder (outside every project)."""
    override = os.environ.get("STUDIO_USER_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "ProposalStudio"
    return Path.home() / ".proposal-studio"


def _load() -> dict[str, Any]:
    try:
        data = json.loads((user_dir() / SETTINGS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, Any]) -> None:
    folder = user_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{SETTINGS}.tmp"
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(folder / SETTINGS)


def default_home() -> Path:
    """``~/Documents/Proposal Studio`` (or ``~/Proposal Studio`` without a Documents folder)."""
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / APP_FOLDER


def home_dir() -> Path:
    """The Proposal Studio folder: shared library and default location of new projects."""
    saved = _load().get("home")
    return Path(saved) if saved else default_home()


def set_home(path: str | Path) -> Path:
    """Move the Proposal Studio folder setting to ``path`` (checked; files are not moved)."""
    folder = check_candidate(path)
    data = _load()
    data["home"] = str(folder)
    _save(data)
    return folder


def check_candidate(path: str | Path) -> Path:
    """The absolute folder for ``path``, or :class:`TrustError` if it's unsafe to use."""
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
        raise TrustError("A whole drive is too broad. Pick or create a folder in it.")
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
    for area in (Path.home(), Path(tempfile.gettempdir()), Path("/tmp")):
        if area.resolve() in folder.parents:
            return True
    parts = folder.parts  # ("/", "Volumes", "Drive", "Bids", …)
    return len(parts) >= 4 and parts[1] in ("Volumes", "media", "mnt")
