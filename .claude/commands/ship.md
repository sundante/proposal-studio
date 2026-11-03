---
description: Cut a release (tag v<version> on main after dev is promoted; CI builds the GitHub Release)
argument-hint: <version, e.g. 0.1.0>
---

Ship **v$ARGUMENTS**:

1. Ask me to confirm that `dev` has been promoted to `main`. Then `git switch main && git pull`.
2. Check `src/studio/__init__.py` says `$ARGUMENTS` and `CHANGELOG.md` has a `## [$ARGUMENTS]`
   section (both are prepared on `dev`). If not, prepare them on `dev`, push, and stop so I can
   promote again.
3. Run `/verify`, `python -m build`, and `python scripts/build_release.py --version $ARGUMENTS --out dist`.
4. **Ask me first**, then create and push the tag: `git tag v$ARGUMENTS && git push origin v$ARGUMENTS`.
   This is the one action on `main`.
5. The `Release` workflow builds the sdist, the wheel and `proposal-studio-$ARGUMENTS-windows.zip`,
   installs the zip on a clean Windows runner, and publishes the GitHub Release with the
   CHANGELOG notes. Watch it with `gh run watch` (if `gh` is logged in) or the Actions tab, then
   print the release URL.
6. `git switch dev`.
