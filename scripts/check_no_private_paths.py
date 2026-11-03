"""Block committing client/private content: library/, workspace/, private templates, overrides.

Usage: ``check_no_private_paths.py FILE...`` (pre-commit) or ``--all`` (every tracked file, CI).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath


def is_private(path: str) -> bool:
    """True if ``path`` (repo-relative) must never be committed."""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if not parts:
        return False
    if parts[0] in {"library", "workspace"}:
        return True
    if parts[0] == "templates" and len(parts) > 1 and parts[1] != "sample":
        return True
    return parts[:2] == ("config", "overrides.yaml")


def main(argv: list[str]) -> int:
    """Return 1 and list offending files if any path is private."""
    if argv == ["--all"]:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
        argv = out.stdout.splitlines()
    bad = [p for p in argv if is_private(p)]
    for p in bad:
        print(f"Refusing to commit private path: {p}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
