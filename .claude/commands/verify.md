---
description: Lint, format, test and fix until green
---

Run in order and fix whatever fails, repeating until all pass (max 5 rounds, then report what's left):

1. `ruff check . --fix`
2. `ruff format .`
3. `pytest -q`
4. OSS-hygiene scan of the staged + unstaged diff: no files under `library/`, `workspace/`,
   `templates/` (except `templates/sample/`); no real company/client/person names; no secrets,
   tokens or absolute personal paths; no `:cloud` model names in defaults.

Report: pass/fail per step in one line each. Don't paste full logs unless something is still failing.
