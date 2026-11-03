---
description: Cut a release (CHANGELOG, version bump, tag, GitHub Release)
argument-hint: <version, e.g. 0.1.0>
---

Prepare release **v$ARGUMENTS**:

1. Ask me to confirm `dev` has been promoted to `main`. Then `git switch main && git pull`; check CI is
   green on the latest commit.
2. Bump the version in `pyproject.toml` / `studio/__init__.py` to `$ARGUMENTS`.
3. Move `CHANGELOG.md` "Unreleased" entries under `## [$ARGUMENTS] - <today>`.
4. Run `/verify`. Build locally (`python -m build`) to make sure the sdist/wheel build works.
5. Commit `chore(release): v$ARGUMENTS` on `main` (the one exception to dev-only), push, then create and push the tag `v$ARGUMENTS` (ask me first).
6. Watch the release workflow (`gh run watch`), then confirm the GitHub Release has the wheel,
   sdist and `proposal-studio-$ARGUMENTS-windows.zip`. Print the release URL.
