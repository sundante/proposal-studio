from pathlib import Path

import pytest

from studio import session
from studio.session import SessionError, SessionStore


def test_create_get_list(tmp_path: Path) -> None:
    opp = session.create_opportunity(tmp_path, "acme-2026", "Acme Health Plan AI RFP")
    for sub in session.OPP_SUBDIRS:
        assert (opp.path / sub).is_dir()
    assert session.get_opportunity(tmp_path, "acme-2026").title == "Acme Health Plan AI RFP"
    session.create_opportunity(tmp_path, "beta")
    assert [o.id for o in session.list_opportunities(tmp_path)] == ["acme-2026", "beta"]


@pytest.mark.parametrize("bad", ["Acme", "../x", "a b", "", "-lead", "x" * 70])
def test_invalid_ids(tmp_path: Path, bad: str) -> None:
    with pytest.raises(SessionError):
        session.create_opportunity(tmp_path, bad)


def test_duplicate_and_missing(tmp_path: Path) -> None:
    session.create_opportunity(tmp_path, "acme")
    with pytest.raises(SessionError, match="already exists"):
        session.create_opportunity(tmp_path, "acme")
    with pytest.raises(SessionError, match="/new nope"):
        session.get_opportunity(tmp_path, "nope")


def test_session_store_round_trip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sess = store.load("chat/1234:abc")
    assert sess.active_opp is None
    sess.active_opp = "acme"
    sess.last_outputs["ask"] = "answer"
    store.save(sess)
    again = SessionStore(tmp_path).load("chat/1234:abc")
    assert again.active_opp == "acme" and again.last_outputs == {"ask": "answer"}
    assert all(p.parent == store.dir for p in store.dir.iterdir())


def test_active_opportunity(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sess = store.load("k")
    with pytest.raises(SessionError, match="No active opportunity"):
        session.active_opportunity(tmp_path, sess)
    session.create_opportunity(tmp_path, "acme")
    sess.active_opp = "acme"
    assert session.active_opportunity(tmp_path, sess).id == "acme"


def test_status_empty(tmp_path: Path) -> None:
    opp = session.create_opportunity(tmp_path, "acme")
    info = session.opportunity_status(opp)
    assert info["chunks"] == 0 and info["files"] == {} and info["digest"] is False
