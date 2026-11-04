"""Folder safety checks, the Proposal Studio folder setting, and the project registry."""

import json
import sys
from pathlib import Path

import pytest

from studio import session, trust


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


def test_home_setting_defaults_and_persists(tmp_path: Path) -> None:
    assert trust.home_dir().name == "Proposal Studio"
    assert trust.set_home(tmp_path / "PS") == (tmp_path / "PS").resolve()
    assert trust.home_dir() == (tmp_path / "PS").resolve()


def test_registry_create_list_remove(tmp_path: Path) -> None:
    home = session.init_home(tmp_path / "Proposal Studio")
    assert session.workspace_dir(home) == home / ".studio"
    assert session.workspace_dir(tmp_path) == tmp_path / "workspace"  # CLI layout unchanged
    a = session.create_project(home, "Acme: RFP/2026")
    assert a.path == (home / "Acme- RFP-2026").resolve() and a.id == "acme-rfp-2026"
    b = session.create_project(home, "Acme: RFP/2026")  # same name → new id and folder
    assert b.id == "acme-rfp-2026-2" and b.path.name == "Acme- RFP-2026 2"
    elsewhere = session.create_project(home, "Other", tmp_path / "Bids" / "Other")
    assert [o.id for o in session.list_opportunities(home)] == [a.id, b.id, elsewhere.id]
    registry = json.loads((home / ".studio" / "projects.json").read_text())
    assert registry[elsewhere.id] == str((tmp_path / "Bids" / "Other").resolve())
    session.remove_project(home, b.id)
    assert b.path.exists() and b.id not in {o.id for o in session.list_opportunities(home)}
    session.remove_project(home, elsewhere.id, delete_files=True)
    assert not elsewhere.path.exists()


def test_never_delete_a_folder_that_is_not_the_project(tmp_path: Path) -> None:
    home = session.init_home(tmp_path / "PS")
    opp = session.create_project(home, "Acme", tmp_path / "Acme")
    meta = opp.path / session.OPP_FILE
    meta.write_text(json.dumps({"id": "someone-else"}))  # folder reused by something else
    with pytest.raises(session.SessionError, match="not deleting"):
        session.remove_project(home, opp.id, delete_files=True)
    assert opp.path.exists()


def test_project_folders_cannot_overlap(tmp_path: Path) -> None:
    home = session.init_home(tmp_path / "PS")
    session.create_project(home, "Acme", tmp_path / "Bids")
    for bad in (tmp_path / "Bids" / "inner", tmp_path, home, home / "library"):
        with pytest.raises(session.SessionError):
            session.create_project(home, "x", bad)
