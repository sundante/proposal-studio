"""FAISS vector index per opportunity / library collection, retrieval, and cited answers."""

from __future__ import annotations

import itertools
import json
import os
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from studio.config import RagConfig
from studio.llm import LLMClient, Message
from studio.models import Chunk

StatusFn = Callable[[str], None]

NOT_FOUND = "Not found in the RFP."
_NOT_FOUND_TOKEN = "NOT_FOUND"
LIBRARY_COLLECTIONS = ("proposals", "reference")


@dataclass(frozen=True)
class Hit:
    """A retrieved chunk and its cosine similarity to the query."""

    chunk: Chunk
    score: float


def _normalise(vectors: Sequence[Sequence[float]]) -> np.ndarray:
    arr = np.asarray(vectors, dtype="float32")
    if arr.ndim != 2:
        raise ValueError("expected a 2-D array of embeddings")
    faiss.normalize_L2(arr)
    return arr


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class VectorIndex:
    """Cosine-similarity FAISS index with chunk metadata, stored in one directory.

    Files: ``index.faiss`` (serialised via Python I/O so non-ASCII Windows paths work),
    ``chunks.jsonl`` (chunk metadata keyed by FAISS id) and ``manifest.json``
    (per-file hash and ids, embedding model, dimension).
    """

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.embed_model: str | None = None
        self.dim: int | None = None
        self.next_id = 0
        self._files: dict[str, dict[str, Any]] = {}
        self._chunks: dict[int, Chunk] = {}
        self._index: faiss.IndexIDMap2 | None = None
        if (directory / "manifest.json").exists():
            self._load()

    # -- persistence --

    def _load(self) -> None:
        manifest = json.loads((self.dir / "manifest.json").read_text(encoding="utf-8"))
        self.embed_model = manifest.get("embed_model")
        self.dim = manifest.get("dim")
        self.next_id = manifest.get("next_id", 0)
        self._files = manifest.get("files", {})
        chunks_path = self.dir / "chunks.jsonl"
        if chunks_path.exists():
            for line in chunks_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    cid = int(row.pop("_id"))
                    self._chunks[cid] = Chunk.model_validate(row)
        index_path = self.dir / "index.faiss"
        if index_path.exists():
            raw = np.frombuffer(index_path.read_bytes(), dtype="uint8")
            self._index = faiss.deserialize_index(raw)

    def save(self) -> None:
        """Write the index, metadata and manifest to disk."""
        self.dir.mkdir(parents=True, exist_ok=True)
        if self._index is not None:
            _write_atomic(self.dir / "index.faiss", faiss.serialize_index(self._index).tobytes())
        lines = [
            json.dumps({"_id": cid, **chunk.model_dump()}, ensure_ascii=False)
            for cid, chunk in sorted(self._chunks.items())
        ]
        _write_atomic(self.dir / "chunks.jsonl", ("\n".join(lines) + "\n").encode("utf-8"))
        manifest = {
            "embed_model": self.embed_model,
            "dim": self.dim,
            "next_id": self.next_id,
            "files": self._files,
        }
        _write_atomic(self.dir / "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))

    # -- queries --

    def __len__(self) -> int:
        return len(self._chunks)

    def files(self) -> list[str]:
        """Names of indexed files."""
        return sorted(self._files)

    def file_hash(self, name: str) -> str | None:
        """Stored hash for ``name``, or None if not indexed."""
        entry = self._files.get(name)
        return entry["hash"] if entry else None

    def file_chunk_count(self, name: str) -> int:
        """Number of chunks indexed for ``name``."""
        entry = self._files.get(name)
        return len(entry["ids"]) if entry else 0

    def search(self, vector: Sequence[float], top_k: int) -> list[Hit]:
        """Top-``top_k`` chunks by cosine similarity."""
        if self._index is None or not self._chunks:
            return []
        query = _normalise([vector])
        scores, ids = self._index.search(query, min(top_k, len(self._chunks)))
        return [
            Hit(self._chunks[int(i)], float(s))
            for s, i in zip(scores[0], ids[0], strict=True)
            if i != -1 and int(i) in self._chunks
        ]

    # -- updates --

    def clear(self) -> None:
        """Drop every vector and file entry (keeps nothing)."""
        self._files, self._chunks, self._index = {}, {}, None
        self.dim, self.next_id = None, 0

    def ensure_model(self, embed_model: str) -> bool:
        """Clear the index if it was built with another embedding model. True if cleared."""
        changed = self.embed_model is not None and self.embed_model != embed_model
        if changed:
            self.clear()
        self.embed_model = embed_model
        return changed

    def remove_file(self, name: str) -> None:
        """Remove a file's chunks and vectors."""
        entry = self._files.pop(name, None)
        if not entry:
            return
        ids = np.asarray(entry["ids"], dtype="int64")
        if self._index is not None and len(ids):
            self._index.remove_ids(ids)
        for cid in entry["ids"]:
            self._chunks.pop(int(cid), None)

    def replace_file(
        self, name: str, digest: str, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> None:
        """Replace everything indexed for ``name`` with ``chunks`` and their ``vectors``."""
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        self.remove_file(name)
        ids = list(range(self.next_id, self.next_id + len(chunks)))
        if chunks:
            arr = _normalise(vectors)
            if self.dim is None:
                self.dim = int(arr.shape[1])
            elif arr.shape[1] != self.dim:
                raise ValueError(
                    f"embedding dimension {arr.shape[1]} != index dimension {self.dim}"
                )
            if self._index is None:
                self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))
            self._index.add_with_ids(arr, np.asarray(ids, dtype="int64"))
            self._chunks.update(zip(ids, chunks, strict=True))
            self.next_id += len(chunks)
        self._files[name] = {"hash": digest, "ids": ids}


def library_index(root: Path, collection: str) -> VectorIndex:
    """Index for a library collection (``proposals`` or ``reference``)."""
    if collection not in LIBRARY_COLLECTIONS:
        raise ValueError(f"Unknown library collection '{collection}'.")
    return VectorIndex(root / "library" / ".index" / collection)


def retrieve(index: VectorIndex, query: str, llm: LLMClient, top_k: int = 6) -> list[Hit]:
    """Embed ``query`` and return the ``top_k`` most similar chunks."""
    if not len(index):
        return []
    [vector] = llm.embed([query])
    return index.search(vector, top_k)


# --- answers --------------------------------------------------------------------------------

_SYSTEM = (
    "You answer questions about an RFP using ONLY the numbered context excerpts. "
    "After every sentence, cite the excerpt number(s) it came from in square brackets, "
    "for example [2] or [1, 3]. Do not use outside knowledge and do not invent facts. "
    "If the excerpts do not answer the question, reply with exactly NOT_FOUND."
)
_BRACKETS = re.compile(r"\[([^\[\]\n]{1,200})\]")
_NUMBERED = re.compile(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]")


def build_messages(question: str, hits: Sequence[Hit]) -> list[Message]:
    """Prompt with numbered context excerpts (the model cites numbers, Python adds labels)."""
    context = "\n\n".join(
        f"[{n}] {hit.chunk.cite}\n{hit.chunk.text}" for n, hit in enumerate(hits, start=1)
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Context:\n\n{context}\n\nQuestion: {question}"},
    ]


def rewrite_numbered_cites(text: str, hits: Sequence[Hit]) -> str:
    """Replace ``[2]`` / ``[1, 3]`` with the excerpts' ``[section, p.N]`` labels.

    Out-of-range numbers are kept as-is so :func:`check_citations` reports them.
    """

    def label(match: re.Match[str]) -> str:
        numbers = [int(n) for n in match.group(1).split(",")]
        if not all(1 <= n <= len(hits) for n in numbers):
            return match.group(0)
        return "".join(dict.fromkeys(str(hits[n - 1].chunk.cite) for n in numbers))

    return _NUMBERED.sub(label, text)


class _CiteRewriter:
    """Rewrites numbered citations in a token stream, holding back any unclosed ``[``."""

    def __init__(self, hits: Sequence[Hit]) -> None:
        self.hits = hits
        self.pending = ""

    def feed(self, piece: str) -> str:
        self.pending += piece
        cut = self.pending.rfind("[")
        if cut == -1 or "]" in self.pending[cut:] or len(self.pending) - cut > 40:
            out, self.pending = self.pending, ""
        else:
            out, self.pending = self.pending[:cut], self.pending[cut:]
        return rewrite_numbered_cites(out, self.hits)

    def flush(self) -> str:
        out, self.pending = self.pending, ""
        return rewrite_numbered_cites(out, self.hits)


def check_citations(text: str, allowed: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split the bracketed citations in ``text`` into (valid, unknown) against ``allowed``."""
    allowed_inner = {a.strip("[]").strip().lower() for a in allowed}
    valid, unknown = [], []
    for match in _BRACKETS.finditer(text):
        inner = match.group(1).strip()
        (valid if inner.lower() in allowed_inner else unknown).append(f"[{inner}]")
    return valid, unknown


def answer(
    question: str,
    index: VectorIndex,
    llm: LLMClient,
    cfg: RagConfig,
    *,
    top_k: int | None = None,
    on_status: StatusFn | None = None,
) -> Iterator[str]:
    """Stream a cited answer to ``question`` from the index, or :data:`NOT_FOUND`.

    No LLM call is made when nothing retrieved clears ``cfg.min_score``. The model cites excerpt
    numbers, which are rewritten to ``[section, p.N]`` here. If the answer has no valid
    citation, a "Sources" footer listing the retrieved sections is appended.
    """
    status = on_status or (lambda _msg: None)
    status("Searching the RFP…")
    hits = retrieve(index, question, llm, top_k or cfg.top_k)
    hits = [h for h in hits if h.score >= cfg.min_score]
    if not hits:
        yield NOT_FOUND
        return

    status(f"Answering from {len(hits)} excerpts…")
    stream = llm.generate_text("worker", build_messages(question, hits), stream=True)
    buffered = ""
    for piece in stream:  # hold back the start so a NOT_FOUND reply is never shown raw
        buffered += piece
        if len(buffered.lstrip()) >= len(_NOT_FOUND_TOKEN):
            break
    if buffered.strip().startswith(_NOT_FOUND_TOKEN):
        for _ in stream:
            pass
        yield NOT_FOUND
        return

    rewriter = _CiteRewriter(hits)
    full = ""
    for piece in itertools.chain([buffered], stream):
        out = rewriter.feed(piece)
        full += out
        if out:
            yield out
    tail = rewriter.flush()
    full += tail
    if tail:
        yield tail

    cites = list(dict.fromkeys(str(h.chunk.cite) for h in hits))
    valid, unknown = check_citations(full, cites)
    if not valid:
        yield "\n\nSources (the model gave no inline citations): " + ", ".join(cites)
    elif unknown:
        yield "\n\nNote: these citations don't match a retrieved section: " + ", ".join(
            dict.fromkeys(unknown)
        )
