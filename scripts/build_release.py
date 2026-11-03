"""Build the Windows bundle zip and release notes from git-tracked files only.

Usage: ``python scripts/build_release.py --version 0.1.0 --out dist``

Only tracked files under an explicit allowlist go in, and every path is checked against the
private-path guard. Client data (library/, workspace/, your templates, overrides,
.owui-data/) can never end up in a release, even if it sits in the working tree.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_no_private_paths import is_private  # noqa: E402

INCLUDE_DIRS = ("src/", "scripts/", "owui/", "config/", "templates/sample/", "docs/", "tests/")
INCLUDE_FILES = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
)


def release_files(root: Path = ROOT) -> list[str]:
    """Tracked files that belong in the bundle."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    picked = [p for p in tracked if p in INCLUDE_FILES or p.startswith(INCLUDE_DIRS)]
    private = [p for p in picked if is_private(p)]
    if private:
        raise SystemExit(f"Refusing to build: private paths are tracked: {private}")
    return sorted(picked)


def package_version(root: Path = ROOT) -> str:
    text = (root / "src" / "studio" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', text)
    if not match:
        raise SystemExit("No __version__ in src/studio/__init__.py")
    return match.group(1)


def release_notes(version: str, root: Path = ROOT) -> str:
    """The CHANGELOG section for ``version``."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    if not match:
        raise SystemExit(f"CHANGELOG.md has no section for [{version}]")
    return match.group(1).strip() + "\n"


def build_zip(version: str, out_dir: Path, root: Path = ROOT) -> Path:
    """Write ``proposal-studio-<version>-windows.zip`` (single top-level folder)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"proposal-studio-{version}-windows.zip"
    prefix = f"proposal-studio-{version}"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in release_files(root):
            zf.write(root / rel, f"{prefix}/{rel}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", default="dist")
    args = parser.parse_args()
    version = args.version.removeprefix("v")
    if version != package_version():
        raise SystemExit(f"Tag {version} != package version {package_version()}")
    out = Path(args.out)
    zip_path = build_zip(version, out)
    (out / "RELEASE_NOTES.md").write_text(release_notes(version), encoding="utf-8")
    print(f"Wrote {zip_path} ({zip_path.stat().st_size // 1024} KB) and {out / 'RELEASE_NOTES.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
