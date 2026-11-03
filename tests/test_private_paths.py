import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_no_private_paths",
    Path(__file__).resolve().parents[1] / "scripts" / "check_no_private_paths.py",
)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


@pytest.mark.parametrize(
    "path",
    [
        "library/proposals/deck.pptx",
        "workspace/acme/digest.json",
        "templates/firm.potx",
        "config/overrides.yaml",
        "library\\blocks\\x.yaml",
    ],
)
def test_private_paths_blocked(path: str) -> None:
    assert guard.is_private(path)
    assert guard.main([path]) == 1


@pytest.mark.parametrize(
    "path",
    ["templates/sample/sample.pptx", "config/models.yaml", "src/studio/llm.py", "templates"],
)
def test_public_paths_allowed(path: str) -> None:
    assert not guard.is_private(path)
