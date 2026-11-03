---
description: Self-review the current branch against the spec before merging
---

Review `git diff main...HEAD` as a strict senior reviewer who did not write this code:

1. **Spec conformance:** for the phase being built, list each requirement in `BUILD_PLAN.md` and
   the referenced `PROJECT_SPEC.md` sections as ✅ / ⚠️ / ❌ with a file:line pointer.
2. **Correctness:** bugs, unhandled errors, Windows-specific pitfalls (paths, subprocess, encodings,
   `.cmd` shims), and offline violations (any network call besides localhost Ollama).
3. **Safety:** sandbox escapes, PHI handling, cloud-model leakage, secrets.
4. **Tests:** important paths with no test.
5. **OSS hygiene:** as in `/verify` step 4.

Then fix every ❌ and clear-cut ⚠️ directly, re-run `/verify`, and give a short list of what you
changed and what you left for me to decide.
