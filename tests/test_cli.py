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


def test_new_ingest_ask_status_flow(studio_home: Path, rfp_files, monkeypatch) -> None:
    from studio import cli
    from tests.fakes import FakeLLM

    llm = FakeLLM(text="Proposals are due March 15, 2027 [2 Submission Instructions, p.1].")
    monkeypatch.setattr(cli, "get_llm", lambda: llm)
    monkeypatch.setenv("STUDIO_SESSION", "test")

    result = runner.invoke(app, ["new", "acme-demo", "Acme Health Plan AI RFP"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["ingest", str(rfp_files["pdf"])])
    assert result.exit_code == 0, result.output
    assert "new: acme_rfp.pdf" in result.output and "Next:" in result.output

    result = runner.invoke(app, ["ask", "When are proposals due?"])
    assert result.exit_code == 0, result.output
    assert "[2 Submission Instructions, p.1]" in result.output

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "acme_rfp.pdf" in result.output and "Digest: no" in result.output

    runner.invoke(app, ["new", "beta"])
    result = runner.invoke(app, ["use"])
    assert "* beta" in result.output and "  acme-demo" in result.output
    assert runner.invoke(app, ["use", "acme-demo"]).exit_code == 0


def test_ingest_phi_exit_code(studio_home: Path, tmp_path: Path, monkeypatch) -> None:
    from studio import cli
    from tests.fakes import FakeLLM

    monkeypatch.setattr(cli, "get_llm", FakeLLM)
    monkeypatch.setenv("STUDIO_SESSION", "test")
    runner.invoke(app, ["new", "acme"])
    leaky = tmp_path / "leaky.txt"
    leaky.write_text("Member SSN 123-45-6789\n")
    result = runner.invoke(app, ["ingest", str(leaky)])
    assert result.exit_code == 2 and "--yes" in result.output
    assert runner.invoke(app, ["ingest", str(leaky), "--yes"]).exit_code == 0


def test_ask_without_opportunity(studio_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_SESSION", "empty")
    result = runner.invoke(app, ["ask", "anything"])
    assert result.exit_code == 1 and "/new" in result.output


def test_digest_cli(studio_home: Path, tmp_path: Path, monkeypatch) -> None:
    from studio import cli
    from tests.fakes import FakeLLM
    from tests.test_digest import GROUP_A

    monkeypatch.setattr(cli, "get_llm", lambda: FakeLLM({"DigestPart": GROUP_A}))
    monkeypatch.setenv("STUDIO_SESSION", "test")
    runner.invoke(app, ["new", "acme"])
    assert runner.invoke(app, ["digest"]).exit_code == 1  # nothing ingested
    rfp = tmp_path / "rfp.txt"
    rfp.write_text("1 Submission\nDue March 15, 2027.\n\n2 Background\nManual review today.\n")
    runner.invoke(app, ["ingest", str(rfp)])

    result = runner.invoke(app, ["digest", "--xlsx"])
    assert result.exit_code == 0, result.output
    assert "## RFP digest — Enterprise AI Platform" in result.output
    assert "acme-requirements-v1.xlsx" in result.output

    result = runner.invoke(app, ["digest", "--show"])
    assert result.exit_code == 0 and "Acme Health Plan" in result.output
    result = runner.invoke(app, ["status"])
    assert "Digest: yes" in result.output and "stale" not in result.output


def test_template_and_render_cli(tmp_path: Path, monkeypatch) -> None:
    from tests.conftest import REPO_ROOT, SAMPLE_DECK

    monkeypatch.setenv("STUDIO_HOME", str(REPO_ROOT))
    tpl = tmp_path / "sample.pptx"
    assert runner.invoke(app, ["template", "sample", "--out", str(tpl)]).exit_code == 0
    result = runner.invoke(app, ["template", "inspect", str(tpl)])
    assert result.exit_code == 0 and "[4] Comparison" in result.output
    assert (tmp_path / "sample.layouts.json").exists()

    args = ["render", "--deck", str(SAMPLE_DECK), "--out", str(tmp_path / "out"), "--template"]
    result = runner.invoke(app, [*args, str(tpl)])
    assert result.exit_code == 0, result.output
    assert "11 slides, ✅ no errors" in result.output
    assert (tmp_path / "out" / "acme-demo-v1.pptx").exists()

    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"opportunity": "x", "slides": [{"id": "a", "slide_type": "why_us", "title": "W"}]}'
    )
    other = tmp_path / "other.pptx"
    other.write_bytes(b"junk")
    result = runner.invoke(
        app, ["render", "--deck", str(bad), "--out", str(tmp_path), "--template", str(other)]
    )
    assert result.exit_code == 1 and "Save As" in result.output


def test_render_without_deck(studio_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_SESSION", "t")
    runner.invoke(app, ["new", "acme"])
    result = runner.invoke(app, ["render"])
    assert result.exit_code == 1 and "/deck" in result.output


def test_harvest_outline_deck_edit_render_cli(studio_home: Path, monkeypatch) -> None:
    from studio import cli
    from tests.conftest import REPO_ROOT
    from tests.fakes import FakeLLM
    from tests.fixtures.make_library import make_library
    from tests.test_blocks import CANNED
    from tests.test_digest import sample_digest

    (studio_home / "templates" / "sample").mkdir(parents=True)
    tpl = REPO_ROOT / "templates" / "sample" / "proposal-sample.pptx"
    (studio_home / "templates" / "sample" / tpl.name).write_bytes(tpl.read_bytes())
    make_library(studio_home / "library" / "proposals")
    plat = {
        "title": "A complete AI platform",
        "bullets": ["Development workbench", "MLOps and LLMOps pipelines", "Observability"],
        "used_blocks": [1],
    }
    llm = FakeLLM(
        {
            "HarvestResult": CANNED,
            "WriteUnderstandingContent": {"title": "Understanding", "bullets": ["a", "b", "c"]},
            "WriteBeforeAfterContent": {
                "title": "Before and after",
                "before": ["Manual", "Slow", "Siloed"],
                "after": ["Assisted", "Fast", "Unified"],
            },
            "WritePlatformContent": plat,
            "WriteGovernanceContent": {"title": "Governance", "bullets": ["HIPAA", "b", "c"]},
            "WriteMaturityContent": {
                "title": "Maturity",
                "stages": [
                    {"name": n, "description": "d"} for n in ("Foundation", "Scale", "Optimize")
                ],
            },
        }
    )
    monkeypatch.setattr(cli, "get_llm", lambda: llm)
    monkeypatch.setenv("STUDIO_SESSION", "test")

    result = runner.invoke(app, ["harvest", "--client", "Example Hospital"])
    assert result.exit_code == 0, result.output
    assert "5 new" in result.output and "Needs review (1)" in result.output
    assert "[platform]" in runner.invoke(app, ["blocks"]).output

    runner.invoke(app, ["new", "acme"])
    opp = studio_home / "workspace" / "acme"
    (opp / "digest.json").write_text(sample_digest().model_dump_json())
    result = runner.invoke(app, ["outline"])
    assert result.exit_code == 0 and "✅ **governance**" in result.output
    assert runner.invoke(app, ["toggle", "title", "off"]).exit_code == 1
    assert runner.invoke(app, ["toggle", "next_steps", "off"]).exit_code == 0

    result = runner.invoke(app, ["deck"])
    assert result.exit_code == 0, result.output
    assert "Please review:" in result.output and "Next: `studio render`" in result.output

    result = runner.invoke(app, ["edit", "platform", "shorter"])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["render"])
    assert result.exit_code == 0, result.output
    assert "no errors" in result.output and (opp / "out" / "acme-v1.pptx").exists()


def test_library_and_research_cli(studio_home: Path, monkeypatch) -> None:
    from studio import cli
    from tests.fixtures.make_reference import make_reference
    from tests.test_research import llm

    make_reference(studio_home / "library" / "reference")
    monkeypatch.setattr(cli, "get_llm", llm)
    monkeypatch.setenv("STUDIO_SESSION", "research")
    result = runner.invoke(app, ["library", "index"])
    assert result.exit_code == 0, result.output
    assert "reference: 2 new" in result.output and "proposals: 0 new" in result.output
    assert "standards/fhir_r4_notes.pdf" in runner.invoke(app, ["library", "status"]).output

    result = runner.invoke(app, ["research", "How do we handle FHIR R4 and HIPAA?"])
    assert result.exit_code == 0, result.output
    assert "## Summary" in result.output and "Saved:" in result.output
    assert list((studio_home / "workspace" / "research").glob("*.md"))
