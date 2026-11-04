"""Ollama client wrapper: structured output, streaming text, embeddings, guards.

Callers depend on the :class:`LLMClient` protocol; :class:`OllamaClient` is the real
implementation and tests use ``tests/fakes.py::FakeLLM``. Both share the retry logic in
:class:`BaseLLM`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from studio.config import ModelsConfig, RoleConfig
from studio.guards import check_model_allowed, is_cloud_model

T = TypeVar("T", bound=BaseModel)
Message = dict[str, str]
StatusFn = Callable[[str], None]

MAX_STRUCTURED_RETRIES = 2
EMBED_BATCH = 32


class LLMError(RuntimeError):
    """An LLM call failed. The message is one plain sentence plus the fix."""


class OllamaUnavailable(LLMError):
    """Ollama is not reachable."""


class ModelNotPulled(LLMError):
    """The requested model is not available locally."""


class StructuredOutputError(LLMError):
    """The model kept returning output that does not match the schema."""


class LLMClient(Protocol):
    """What the rest of `studio` needs from an LLM backend."""

    def generate_structured(self, role: str, messages: Sequence[Message], schema: type[T]) -> T:
        """Return a validated instance of ``schema``."""
        ...

    def generate_text(
        self, role: str, messages: Sequence[Message], stream: bool = True
    ) -> Iterator[str]:
        """Yield text chunks (a single chunk when ``stream`` is False)."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...


# --- single-flight lock ---------------------------------------------------------------------

_GENERATION_LOCK = threading.Lock()


@contextmanager
def single_flight(on_wait: StatusFn | None = None) -> Iterator[None]:
    """Allow only one generation at a time in this process; report when a caller has to wait."""
    if not _GENERATION_LOCK.acquire(blocking=False):
        if on_wait:
            on_wait("waiting for model…")
        _GENERATION_LOCK.acquire()
    try:
        yield
    finally:
        _GENERATION_LOCK.release()


# --- shared behaviour -----------------------------------------------------------------------


class BaseLLM:
    """Implements ``generate_structured`` (schema prompt, validation, retries) on top of
    a backend-specific :meth:`_chat_json`."""

    def _chat_json(self, role: str, messages: list[Message], schema: dict[str, Any]) -> str:
        raise NotImplementedError

    def generate_structured(self, role: str, messages: Sequence[Message], schema: type[T]) -> T:
        """Call the model constrained to ``schema``; retry up to 2 times with the error appended."""
        json_schema = schema.model_json_schema()
        convo = list(messages)
        last_error = ""
        for _attempt in range(MAX_STRUCTURED_RETRIES + 1):
            raw = self._chat_json(role, convo, json_schema)
            try:
                return schema.model_validate_json(raw)
            except ValidationError as exc:
                last_error = _short_errors(exc)
                convo = [
                    *convo,
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": "Your JSON did not match the schema: "
                        f"{last_error}. Reply again with corrected JSON only.",
                    },
                ]
        raise StructuredOutputError(
            f"The model returned invalid {schema.__name__} output {MAX_STRUCTURED_RETRIES + 1} "
            f"times ({last_error}). Try again, or switch the role to a larger model with /config."
        )


def _short_errors(exc: ValidationError, limit: int = 5) -> str:
    parts = [
        f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}"
        for e in exc.errors()[:limit]
    ]
    return "; ".join(parts)


# --- Ollama ---------------------------------------------------------------------------------


class OllamaClient(BaseLLM):
    """Talks to Ollama's native API (``/api/chat``, ``/api/embed``) with httpx."""

    def __init__(
        self,
        cfg: ModelsConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        on_status: StatusFn | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_status = on_status
        self._http = httpx.Client(
            base_url=cfg.ollama_url.rstrip("/"),
            timeout=httpx.Timeout(cfg.timeout_s, connect=5.0),
            transport=transport,
        )

    # -- helpers --

    def _role(self, role: str) -> RoleConfig:
        try:
            rc = self.cfg.roles[role]
        except KeyError as exc:
            raise LLMError(f"Unknown model role '{role}'. Check config/models.yaml.") from exc
        check_model_allowed(rc.model, block_cloud=self.cfg.block_cloud_models)
        return rc

    def _chat_payload(self, rc: RoleConfig, messages: Sequence[Message]) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if rc.num_ctx is not None:
            options["num_ctx"] = rc.num_ctx
        if rc.temperature is not None:
            options["temperature"] = rc.temperature
        if rc.num_gpu is not None:
            options["num_gpu"] = rc.num_gpu
        return {
            "model": rc.model,
            "messages": list(messages),
            "think": self.cfg.think,
            "keep_alive": self.cfg.keep_alive,
            "options": options,
        }

    def _raise_for(self, resp: httpx.Response, model: str) -> None:
        if resp.status_code < 400:
            return
        resp.read()
        try:
            detail = str(resp.json().get("error", resp.text))
        except ValueError:
            detail = resp.text
        if resp.status_code == 404 or "not found" in detail.lower():
            raise ModelNotPulled(f"Model {model} isn't pulled. Run `ollama pull {model}`.")
        raise LLMError(f"Ollama returned an error for {model}: {detail}")

    @contextmanager
    def _connection_errors(self) -> Iterator[None]:
        try:
            yield
        except httpx.ConnectError as exc:
            raise OllamaUnavailable(
                f"Ollama isn't running at {self.cfg.ollama_url}. Start it with `ollama serve`."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"Ollama timed out after {self.cfg.timeout_s:.0f}s. Try a smaller model or prompt."
            ) from exc

    # -- API --

    def _chat_json(self, role: str, messages: list[Message], schema: dict[str, Any]) -> str:
        rc = self._role(role)
        payload = {**self._chat_payload(rc, messages), "stream": False, "format": schema}
        with single_flight(self.on_status), self._connection_errors():
            resp = self._http.post("/api/chat", json=payload)
            self._raise_for(resp, rc.model)
            return resp.json()["message"]["content"]

    def generate_text(
        self, role: str, messages: Sequence[Message], stream: bool = True
    ) -> Iterator[str]:
        """Yield the answer as it streams from Ollama (one chunk if ``stream`` is False)."""
        rc = self._role(role)
        payload = {**self._chat_payload(rc, messages), "stream": stream}
        with single_flight(self.on_status), self._connection_errors():
            if not stream:
                resp = self._http.post("/api/chat", json=payload)
                self._raise_for(resp, rc.model)
                yield resp.json()["message"]["content"]
                return
            with self._http.stream("POST", "/api/chat", json=payload) as resp:
                self._raise_for(resp, rc.model)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise LLMError(f"Ollama error: {data['error']}")
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        break

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed texts with the ``embed`` role model, in batches."""
        rc = self._role("embed")
        vectors: list[list[float]] = []
        with self._connection_errors():
            for start in range(0, len(texts), EMBED_BATCH):
                batch = list(texts[start : start + EMBED_BATCH])
                resp = self._http.post(
                    "/api/embed",
                    json={"model": rc.model, "input": batch, "keep_alive": self.cfg.keep_alive},
                )
                self._raise_for(resp, rc.model)
                vectors.extend(resp.json()["embeddings"])
        return vectors

    # -- diagnostics (used by `studio doctor`) --

    def version(self) -> str:
        """Ollama server version string."""
        with self._connection_errors():
            resp = self._http.get("/api/version", timeout=5.0)
            resp.raise_for_status()
            return str(resp.json().get("version", "unknown"))

    def list_models(self) -> list[str]:
        """Names of locally pulled models."""
        with self._connection_errors():
            resp = self._http.get("/api/tags", timeout=5.0)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]

    def model_details(self) -> list[dict[str, Any]]:
        """Pulled models with size and details, marked ``loaded`` if in memory now."""
        with self._connection_errors():
            tags = self._http.get("/api/tags", timeout=5.0)
            tags.raise_for_status()
            ps = self._http.get("/api/ps", timeout=5.0)
            ps.raise_for_status()
        loaded = {m["name"]: m for m in ps.json().get("models", [])}
        out = []
        for m in tags.json().get("models", []):
            details = m.get("details") or {}
            running = loaded.get(m["name"])
            out.append(
                {
                    "name": m["name"],
                    "size": int(m.get("size") or 0),
                    "family": details.get("family", ""),
                    "parameters": details.get("parameter_size", ""),
                    "quantization": details.get("quantization_level", ""),
                    "cloud": is_cloud_model(m["name"]),
                    "loaded": running is not None,
                    "expires": (running or {}).get("expires_at"),
                }
            )
        return out

    def loaded_models(self) -> list[str]:
        """Names of models currently loaded in memory (``/api/ps``)."""
        with self._connection_errors():
            resp = self._http.get("/api/ps", timeout=5.0)
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]


def model_is_pulled(model: str, pulled: Sequence[str]) -> bool:
    """True if ``model`` matches a pulled name (``nomic-embed-text`` == ``…:latest``)."""
    names = set(pulled)
    return model in names or (":" not in model and f"{model}:latest" in names)
