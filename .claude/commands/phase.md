---
description: Build one phase of Proposal Studio end to end (branch → code → tests → PR)
argument-hint: <phase number, e.g. 3>
---

Build **Phase $ARGUMENTS** of Proposal Studio.

1. Read `PROGRESS.md`, then the `## Phase $ARGUMENTS` section of `BUILD_PLAN.md`, then only the
   `PROJECT_SPEC.md` sections that phase references.
2. If an earlier phase is not marked done in `PROGRESS.md`, stop and tell me.
3. Make sure you're on `dev` (`git switch dev`, `git pull`). Never create branches or touch `main`.
4. In ≤10 lines: the files you'll create/change and any real spec ambiguity. Then proceed without
   waiting unless something truly blocks you.
5. Do any VERIFY steps the phase lists first, and log the findings in `DECISIONS.md`.
6. Implement with small Conventional Commits as you go. Write the tests alongside the code.
7. Run `/verify`'s checks (ruff check --fix, ruff format, pytest -q) and fix until green.
8. Update `PROGRESS.md` (phase done, what's next, known issues) and `CHANGELOG.md` (Unreleased).
9. Push with `git push origin dev`. No PR; the maintainer promotes `dev` → `main`.
10. Finish with a 5-line summary and the exact commands I can run to try it.
