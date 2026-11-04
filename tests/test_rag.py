from pathlib import Path

import pytest

from studio.config import RagConfig
from studio.ingest import ingest
from studio.models import Chunk
from studio.rag import NOT_FOUND, VectorIndex, answer, check_citations, library_index, retrieve
from tests.fakes import FakeLLM, fake_embedding


@pytest.fixture
def indexed(tmp_path: Path, rfp_files) -> VectorIndex:
    opp = tmp_path / "workspace" / "acme"
    ingest(opp, [rfp_files["pdf"]], FakeLLM(), RagConfig(), "nomic-embed-text")
    return VectorIndex(opp / "index")


def test_retrieve_finds_relevant_chunk(indexed: VectorIndex) -> None:
    hits = retrieve(indexed, "When are proposals due via the procurement portal?", FakeLLM(), 3)
    assert hits[0].chunk.section == "2 Submission Instructions"
    assert hits[0].chunk.page == 1
    assert hits[0].score >= hits[-1].score


def test_index_round_trip(tmp_path: Path) -> None:
    index = VectorIndex(tmp_path / "idx")
    words = ["alpha", "bravo", "charlie"]
    chunks = [
        Chunk(id=f"c{i}", file="f.txt", file_hash="h", section="S", page=i, text=f"{w} topic")
        for i, w in enumerate(words)
    ]
    index.replace_file("f.txt", "h", chunks, [fake_embedding(c.text) for c in chunks])
    index.save()
    reloaded = VectorIndex(tmp_path / "idx")
    assert len(reloaded) == 3 and reloaded.file_hash("f.txt") == "h"
    assert reloaded.search(fake_embedding("bravo"), 1)[0].chunk.id == "c1"
    reloaded.remove_file("f.txt")
    assert len(reloaded) == 0 and reloaded.search(fake_embedding("alpha"), 3) == []


def test_library_index_location(tmp_path: Path) -> None:
    assert library_index(tmp_path, "reference").dir == tmp_path / "library" / ".index" / "reference"
    with pytest.raises(ValueError):
        library_index(tmp_path, "secrets")


def test_not_found_without_llm_call(indexed: VectorIndex) -> None:
    llm = FakeLLM(text="should not be used")
    out = "".join(answer("zebra xylophone quokka", indexed, llm, RagConfig(min_score=0.3)))
    assert out == NOT_FOUND
    assert all(call["schema"] is not None for call in llm.calls)  # no generate_text call


def test_answer_with_valid_citation(indexed: VectorIndex) -> None:
    llm = FakeLLM(text="Proposals are due March 15, 2027 [2 Submission Instructions, p.1].")
    out = "".join(answer("When are proposals due?", indexed, llm, RagConfig()))
    assert out.startswith("Proposals are due March 15, 2027")
    assert "Sources" not in out and "Note:" not in out
    prompt = llm.calls[-1]["messages"][1]["content"]
    assert "[2 Submission Instructions, p.1]" in prompt


def test_answer_without_citations_gets_sources_footer(indexed: VectorIndex) -> None:
    llm = FakeLLM(text="They are due in March.")
    out = "".join(answer("When are proposals due?", indexed, llm, RagConfig()))
    assert "Sources (the model gave no inline citations): [" in out


def test_answer_flags_unknown_citations(indexed: VectorIndex) -> None:
    text = "Due March 15 [2 Submission Instructions, p.1] and audited [9 Imaginary, p.99]."
    out = "".join(answer("When are proposals due?", indexed, FakeLLM(text=text), RagConfig()))
    assert "don't match a retrieved section: [9 Imaginary, p.99]" in out


def test_model_not_found_reply_maps_to_message(indexed: VectorIndex) -> None:
    out = "".join(
        answer("When are proposals due?", indexed, FakeLLM(text="NOT_FOUND"), RagConfig())
    )
    assert out == NOT_FOUND


def test_check_citations() -> None:
    valid, unknown = check_citations("a [S, p.1] b [T] c [X, p.2]", ["[S, p.1]", "[T]"])
    assert valid == ["[S, p.1]", "[T]"] and unknown == ["[X, p.2]"]


def test_empty_index_not_found(tmp_path: Path) -> None:
    out = "".join(answer("anything", VectorIndex(tmp_path / "none"), FakeLLM(), RagConfig()))
    assert out == NOT_FOUND


def test_numbered_cites_rewritten_while_streaming(indexed: VectorIndex) -> None:
    llm = FakeLLM(
        text="Proposals are due March 15, 2027 [ 1 ]. Questions close in February [1, 99]."
    )
    pieces = list(answer("When are proposals due?", indexed, llm, RagConfig()))
    out = "".join(pieces)
    assert "2027 [2 Submission Instructions, p.1]." in out
    assert "[1, 99]" in out and "don't match a retrieved section: [1, 99]" in out
    assert len(pieces) > 3  # still streamed, not one blob


def test_rewrite_handles_split_brackets(indexed: VectorIndex) -> None:
    from studio.rag import _CiteRewriter, retrieve

    hits = retrieve(indexed, "When are proposals due?", FakeLLM(), 2)
    rw = _CiteRewriter(hits)
    out = rw.feed("Due soon [") + rw.feed("1") + rw.feed("] done.") + rw.flush()
    assert out == f"Due soon {hits[0].chunk.cite} done."


def test_search_matches_brute_force_and_old_layout_rebuilds(tmp_path: Path) -> None:
    import json as _json

    import numpy as np

    index = VectorIndex(tmp_path / "idx")
    texts = [f"topic {w} words" for w in ("alpha", "bravo", "charlie", "delta", "echo")]
    chunks = [
        Chunk(id=f"c{i}", file="f.txt", file_hash="h", section="S", text=t)
        for i, t in enumerate(texts)
    ]
    vectors = [fake_embedding(t) for t in texts]
    index.replace_file("f.txt", "h", chunks, vectors)
    query = fake_embedding("bravo delta")
    arr = np.asarray(vectors, dtype="float32")
    arr /= np.linalg.norm(arr, axis=1, keepdims=True)
    q = np.asarray(query, dtype="float32") / np.linalg.norm(query)
    expected = [f"c{i}" for i in np.argsort(-(arr @ q), kind="stable")[:3]]
    assert [h.chunk.id for h in index.search(query, 3)] == expected
    assert len(index.search(query, 50)) == 5 and index.search(query, 0) == []

    index.save()
    (tmp_path / "idx" / "vectors.npz").unlink()  # simulate the pre-NumPy (FAISS) layout
    (tmp_path / "idx" / "index.faiss").write_bytes(b"old")
    old = VectorIndex(tmp_path / "idx")
    assert len(old) == 0 and old.file_hash("f.txt") is None  # next ingest re-embeds
    assert _json.loads((tmp_path / "idx" / "manifest.json").read_text())["files"]
