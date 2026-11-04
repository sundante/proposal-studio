"""Document viewer: PDF pages, text layer, find, reading views, and citation sources."""

import shutil
from pathlib import Path

import httpx
import pytest

from studio.ui import docview
from tests.test_ui import client, events, home, new_project, reply_text, ws  # noqa: F401


@pytest.fixture
def project(client: httpx.Client, ws: Path, rfp_files) -> str:  # noqa: F811
    pid, chat = new_project(client, "Acme")
    for key in ("pdf", "docx"):
        f = rfp_files[key]
        client.put(f"/api/projects/{pid}/uploads/{f.name}", content=f.read_bytes())
    client.post(
        f"/api/chats/{chat}/messages", json={"text": "", "files": ["acme_rfp.pdf", "acme_rfp.docx"]}
    )
    return pid


def test_pdf_meta_page_words_and_find(client: httpx.Client, project: str) -> None:  # noqa: F811
    base = f"/api/projects/{project}/files/acme_rfp.pdf"
    meta = client.get(f"{base}/meta").json()
    assert meta["kind"] == "pdf" and meta["pages"] >= 2 and len(meta["page_sizes"]) == meta["pages"]
    png = client.get(f"{base}/pages/1.png", params={"w": 600})
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    again = client.get(f"{base}/pages/1.png", params={"w": 600})
    assert again.content == png.content  # served from the cache
    words = client.get(f"{base}/pages/1/words").json()
    assert words["width"] > 0 and any("Proposals" in w[4] for w in words["words"])
    found = client.get(f"{base}/find", params={"q": "March 15"}).json()["hits"]
    assert found and found[0]["page"] >= 1 and len(found[0]["rects"][0]) == 4
    assert client.get(f"{base}/pages/99.png").status_code == 400
    raw = client.get(f"{base}/raw")
    assert raw.status_code == 200 and raw.content[:4] == b"%PDF"


def test_docx_reading_view_and_find(client: httpx.Client, project: str) -> None:  # noqa: F811
    base = f"/api/projects/{project}/files/acme_rfp.docx"
    secs = client.get(f"{base}/sections").json()["sections"]
    assert secs and any("Submission" in " ".join(s["heading"]) for s in secs)
    hits = client.get(f"{base}/find", params={"q": "march 15"}).json()["hits"]
    assert hits and "section" in hits[0]
    assert client.get(f"{base}/meta").json()["kind"] == "docx"


def test_viewer_refuses_unknown_and_traversal(client: httpx.Client, project: str) -> None:  # noqa: F811
    assert client.get(f"/api/projects/{project}/files/nope.pdf/meta").status_code == 404
    bad = client.get(f"/api/projects/{project}/files/..%2Fopportunity.json/meta")
    assert bad.status_code in (400, 404)


def test_answers_carry_their_sources(client: httpx.Client, project: str) -> None:  # noqa: F811
    chat = client.post(f"/api/projects/{project}/chats").json()["id"]
    resp = client.post(f"/api/chats/{chat}/messages", json={"text": "When are proposals due?"})
    evts = events(resp)
    sources = next(d["sources"] for e, d in evts if e == "sources")
    assert sources[0]["file"] in ("acme_rfp.pdf", "acme_rfp.docx") and sources[0]["label"]
    assert "March 15, 2027" in reply_text(evts)
    saved = client.get(f"/api/chats/{chat}").json()["messages"][-1]
    assert saved["sources"] == sources


def test_render_cache_is_keyed_by_file(tmp_path: Path, rfp_files) -> None:
    pdf = tmp_path / "a.pdf"
    shutil.copy(rfp_files["pdf"], pdf)
    first = docview.render_page(pdf, 1, 300, tmp_path)
    assert list((tmp_path / docview.CACHE_DIR / "pages").glob("*.png"))
    assert docview.render_page(pdf, 1, 300, tmp_path) == first
    with pytest.raises(docview.ViewError):
        docview.render_page(pdf, 0, 300, tmp_path)
