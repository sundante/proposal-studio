"""Test doubles: FakeLLM (canned outputs keyed by schema name) and a fake embedder."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from typing import Any

from studio.llm import BaseLLM, Message


class FakeLLM(BaseLLM):
    """Returns canned JSON per schema name; a list of responses is consumed in order.

    ``FakeLLM({"Answer": ['{"bad": 1}', '{"text": "ok"}']})`` returns invalid output first,
    which exercises the structured retry path. Every call is recorded in ``calls``.
    """

    def __init__(
        self,
        structured: dict[str, Any] | None = None,
        text: str = "fake answer",
        dim: int = 8,
    ) -> None:
        self.structured = {
            k: list(v) if isinstance(v, list) else [v] for k, v in (structured or {}).items()
        }
        self.text = text
        self.dim = dim
        self.calls: list[dict[str, Any]] = []

    def _chat_json(self, role: str, messages: list[Message], schema: dict[str, Any]) -> str:
        name = schema.get("title", "")
        self.calls.append({"role": role, "schema": name, "messages": messages})
        queue = self.structured.get(name)
        if not queue:
            raise AssertionError(f"FakeLLM has no canned output for schema '{name}'")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        return item if isinstance(item, str) else json.dumps(item)

    def generate_text(
        self, role: str, messages: Sequence[Message], stream: bool = True
    ) -> Iterator[str]:
        self.calls.append({"role": role, "schema": None, "messages": list(messages)})
        if stream:
            yield from (w + " " for w in self.text.split())
        else:
            yield self.text

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [fake_embedding(t, self.dim) for t in texts]


def fake_embedding(text: str, dim: int = 8) -> list[float]:
    """Deterministic pseudo-embedding derived from a hash of the text."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in digest[:dim]]
