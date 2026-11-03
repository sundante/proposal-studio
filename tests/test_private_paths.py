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


def test_release_bundle_contains_only_public_files(tmp_path) -> None:
    import importlib.util as iu
    import zipfile

    spec = iu.spec_from_file_location(
        "build_release", Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"
    )
    br = iu.module_from_spec(spec)
    spec.loader.exec_module(br)
    files = br.release_files()
    assert (
        "pyproject.toml" in files
        and "scripts/setup.ps1" in files
        and "owui/router_pipe.py" in files
    )
    assert "templates/sample/proposal-sample.pptx" in files
    assert not [f for f in files if guard.is_private(f) or f.startswith(("vibes/", ".github/"))]
    target = br.build_zip(br.package_version(), tmp_path)
    names = zipfile.ZipFile(target).namelist()
    assert all(n.startswith(f"proposal-studio-{br.package_version()}/") for n in names)
    assert len(names) == len(files)
