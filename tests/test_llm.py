import json
import threading

import httpx
import pytest
from pydantic import BaseModel

from studio.config import ModelsConfig
from studio.guards import GuardError
from studio.llm import (
    ModelNotPulled,
    OllamaClient,
    OllamaUnavailable,
    StructuredOutputError,
    model_is_pulled,
    single_flight,
)
from tests.fakes import FakeLLM


class Answer(BaseModel):
    text: str
    confidence: float


def models_cfg(**kw) -> ModelsConfig:
    data = {
        "roles": {
            "router": {"model": "qwen3:4b", "num_ctx": 4096, "temperature": 0.0},
            "worker": {"model": "qwen3:8b", "num_ctx": 16384, "temperature": 0.3},
            "embed": {"model": "nomic-embed-text"},
        }
    }
    data.update(kw)
    return ModelsConfig.model_validate(data)


# --- FakeLLM / BaseLLM retry logic ----------------------------------------------------------


def test_structured_success_first_try() -> None:
    llm = FakeLLM({"Answer": {"text": "ok", "confidence": 0.9}})
    out = llm.generate_structured("worker", [{"role": "user", "content": "hi"}], Answer)
    assert out == Answer(text="ok", confidence=0.9)
    assert len(llm.calls) == 1


def test_structured_retries_with_error_appended() -> None:
    llm = FakeLLM({"Answer": ['{"text": "ok"}', "not json", '{"text": "ok", "confidence": 1}']})
    out = llm.generate_structured("worker", [{"role": "user", "content": "hi"}], Answer)
    assert out.confidence == 1
    assert len(llm.calls) == 3
    last_msgs = llm.calls[-1]["messages"]
    assert "did not match the schema" in last_msgs[-1]["content"]
    assert "confidence" in llm.calls[1]["messages"][-1]["content"]


def test_structured_gives_up_after_two_retries() -> None:
    llm = FakeLLM({"Answer": '{"text": 1}'})
    with pytest.raises(StructuredOutputError, match="3 times"):
        llm.generate_structured("worker", [{"role": "user", "content": "hi"}], Answer)
    assert len(llm.calls) == 3


# --- OllamaClient over a mock transport -----------------------------------------------------


def test_ollama_structured_payload() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        content = json.dumps({"text": "hello", "confidence": 0.5})
        return httpx.Response(200, json={"message": {"content": content}})

    client = OllamaClient(models_cfg(), transport=httpx.MockTransport(handler))
    out = client.generate_structured("router", [{"role": "user", "content": "q"}], Answer)
    assert out.text == "hello"
    assert seen["model"] == "qwen3:4b"
    assert seen["stream"] is False
    assert seen["think"] is False
    assert seen["format"]["title"] == "Answer"
    assert seen["options"] == {"num_ctx": 4096, "temperature": 0.0}


def test_ollama_streaming_text() -> None:
    lines = [
        {"message": {"content": "Hel"}, "done": False},
        {"message": {"content": "lo"}, "done": False},
        {"message": {"content": ""}, "done": True},
    ]
    body = "\n".join(json.dumps(x) for x in lines).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = OllamaClient(models_cfg(), transport=httpx.MockTransport(handler))
    assert "".join(client.generate_text("worker", [{"role": "user", "content": "q"}])) == "Hello"


def test_ollama_embed_batches() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        batch = json.loads(request.content)["input"]
        sizes.append(len(batch))
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]] * len(batch)})

    client = OllamaClient(models_cfg(), transport=httpx.MockTransport(handler))
    vectors = client.embed([f"t{i}" for i in range(70)])
    assert len(vectors) == 70
    assert sizes == [32, 32, 6]


def test_ollama_model_not_pulled_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'qwen3:8b' not found"})

    client = OllamaClient(models_cfg(), transport=httpx.MockTransport(handler))
    with pytest.raises(ModelNotPulled, match="ollama pull qwen3:8b"):
        list(client.generate_text("worker", [{"role": "user", "content": "q"}], stream=False))


def test_ollama_unavailable_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = OllamaClient(models_cfg(), transport=httpx.MockTransport(handler))
    with pytest.raises(OllamaUnavailable, match="ollama serve"):
        client.version()


def test_ollama_refuses_cloud_model_at_call_time() -> None:
    cfg = models_cfg()
    cfg.roles["worker"].model = "qwen3:480b-cloud"  # bypass validation, as a mutation would
    client = OllamaClient(cfg, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(GuardError):
        list(client.generate_text("worker", [{"role": "user", "content": "q"}]))


def test_model_is_pulled_latest_tag() -> None:
    pulled = ["nomic-embed-text:latest", "qwen3:8b"]
    assert model_is_pulled("nomic-embed-text", pulled)
    assert model_is_pulled("qwen3:8b", pulled)
    assert not model_is_pulled("qwen3:4b", pulled)


def test_single_flight_reports_waiting() -> None:
    events: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with single_flight():
            entered.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    entered.wait(5)
    threading.Timer(0.1, release.set).start()
    with single_flight(events.append):
        pass
    t.join(5)
    assert events == ["waiting for model…"]
