"""Trusted workspace folders."""

import sys
from pathlib import Path

import pytest

from studio import session, trust


def test_trust_creates_marker_and_folders(tmp_path: Path) -> None:
    folder = trust.trust(tmp_path / "Bids" / "Acme")
    assert (folder / ".studio" / "workspace.json").exists()
    assert (folder / "projects").is_dir() and (folder / "library").is_dir()
    assert trust.is_trusted(folder) and trust.last_workspace() == folder
    assert session.workspace_dir(folder) == folder / "projects"
    assert session.workspace_dir(tmp_path) == tmp_path / "workspace"  # CLI layout unchanged
    trust.untrust(folder)
    assert not trust.is_trusted(folder) and trust.last_workspace() is None
    assert folder.exists()  # forgetting never deletes files


def test_marker_alone_is_not_trust(tmp_path: Path) -> None:
    (tmp_path / "w" / ".studio").mkdir(parents=True)
    (tmp_path / "w" / ".studio" / "workspace.json").write_text("{}")
    assert not trust.is_trusted(tmp_path / "w")


@pytest.mark.parametrize("bad", ["", "relative/path", "/", "~"])
def test_unsafe_folders_refused(bad: str) -> None:
    with pytest.raises(trust.TrustError):
        trust.check_candidate(bad)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX system folders")
def test_system_folders_refused() -> None:
    for bad in ("/etc", "/usr/local/x", "/System/Library", "/tmp", "/Volumes/Disk"):
        with pytest.raises(trust.TrustError, match="system folder"):
            trust.check_candidate(bad)
    for ok in ("/tmp/bids", "/Volumes/Disk/Bids/Acme", str(Path.home() / "Bids")):
        trust.check_candidate(ok)


def test_a_file_is_not_a_folder(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x")
    with pytest.raises(trust.TrustError, match="is a file"):
        trust.check_candidate(tmp_path / "f.txt")


def test_open_last_and_recent_order(tmp_path: Path) -> None:
    a, b = trust.trust(tmp_path / "a"), trust.trust(tmp_path / "b")
    trust.touch(a)
    assert [Path(w["path"]) for w in trust.trusted()][0] in (a, b)
    assert trust.open_last() is False
    trust.set_open_last(True)
    assert trust.open_last() is True
