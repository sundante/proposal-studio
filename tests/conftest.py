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
