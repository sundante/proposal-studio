---
description: Resume an interrupted phase from PROGRESS.md and git state
---

A previous session stopped mid-phase (likely a usage limit). Resume without redoing work:

1. Read `PROGRESS.md`, `git status`, `git log --oneline -15`, and confirm you're on `dev`.
2. Work out which phase is in progress and which of its steps are done (from commits and files).
3. In ≤8 lines, state where things stand and what remains.
4. Continue from the next unfinished step of `/phase` for that phase, through to `git push origin dev`.
