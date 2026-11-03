"""Shared fixtures. Tests never need Ollama, internet, or a real template."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def studio_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway project root with a copy of the default config, set as $STUDIO_HOME."""
    shutil.copytree(REPO_ROOT / "config", tmp_path / "config")
    (tmp_path / "config" / "overrides.yaml").unlink(missing_ok=True)
    monkeypatch.setenv("STUDIO_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture(scope="session")
def rfp_files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Synthetic Acme Health Plan RFP fixtures (PDF, DOCX, XLSX, PPTX), generated once."""
    from tests.fixtures.make_rfp import make_all

    return make_all(tmp_path_factory.mktemp("rfp"))


SAMPLE_DECK = REPO_ROOT / "tests" / "fixtures" / "sample_deck.json"


@pytest.fixture(scope="session")
def sample_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A freshly generated sample template (not the committed copy)."""
    from studio.render.sample_template import build_sample_template

    return build_sample_template(tmp_path_factory.mktemp("tpl") / "proposal-sample.pptx")
