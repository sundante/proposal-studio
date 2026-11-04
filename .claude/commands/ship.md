---
description: Cut a release (tag v<version> on main after dev is promoted; build the files locally)
argument-hint: <version, e.g. 0.1.0>
---

Ship **v$ARGUMENTS**. There is no GitHub Actions automation, so everything is built locally:

1. Ask me to confirm that `dev` has been promoted to `main`. Then `git switch main && git pull`.
2. Check `src/studio/__init__.py` says `$ARGUMENTS` and `CHANGELOG.md` has a `## [$ARGUMENTS]`
   section (both are prepared on `dev`). If not, prepare them on `dev`, push, and stop so I can
   promote again.
3. Run `/verify`, `python -m build`, and `python scripts/build_release.py --version $ARGUMENTS --out dist`.
4. **Ask me first**, then create and push the tag: `git tag v$ARGUMENTS && git push origin v$ARGUMENTS`.
   This is the one action on `main`.
5. Tell me which files to attach (`dist/*.tar.gz`, `dist/*.whl`,
   `dist/proposal-studio-$ARGUMENTS-windows.zip`, notes in `dist/RELEASE_NOTES.md`). I create the
   GitHub Release by hand, or, only if I ask, with `gh release create`.
6. `git switch dev`.
