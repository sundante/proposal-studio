from pathlib import Path

import httpx
from typer.testing import CliRunner

from studio import __version__
from studio import config as cfgmod
from studio.cli import app, run_checks
from studio.llm import OllamaClient

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_config_show_set_reset(studio_home: Path) -> None:
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0 and "qwen3:8b" in result.output

    result = runner.invoke(app, ["config", "set", "worker.model", "qwen3:4b"])
    assert result.exit_code == 0
    assert (studio_home / "config" / "overrides.yaml").exists()

    result = runner.invoke(app, ["config", "set", "worker.model", "big:cloud"])
    assert result.exit_code == 1 and "cloud" in result.output

    result = runner.invoke(app, ["config", "reset"])
    assert result.exit_code == 0
    assert not (studio_home / "config" / "overrides.yaml").exists()


def _client(handler) -> OllamaClient:
    return OllamaClient(cfgmod.load_config().models, transport=httpx.MockTransport(handler))


def test_doctor_all_green(studio_home: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.12.3"})
        names = ["qwen3:8b", "qwen3:4b", "nomic-embed-text:latest"]
        return httpx.Response(200, json={"models": [{"name": n} for n in names]})

    checks = run_checks(_client(handler))
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]
    assert (studio_home / "workspace").is_dir()


def test_doctor_reports_missing_model_and_old_ollama(studio_home: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.4.7"})
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})

    failed = [c for c in run_checks(_client(handler)) if not c.ok]
    fixes = " ".join(c.fix for c in failed)
    assert "ollama pull qwen3:4b" in fixes
    assert "Upgrade Ollama" in fixes


def test_doctor_ollama_down(studio_home: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    checks = run_checks(_client(handler))
    assert not checks[-1].ok and "ollama serve" in checks[-1].fix
