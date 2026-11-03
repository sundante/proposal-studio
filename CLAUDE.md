# Proposal Studio — instructions for Claude Code

Open-source, fully local/offline proposal workbench: Open WebUI + Ollama + a Python package `studio`
that routes chat commands (/ingest, /ask, /digest, /deck, /render, /research, /agent …) to RFP
analysis, deck writing and PPTX rendering.

## Source of truth
- `PROJECT_SPEC.md` — the decided design. Read the sections relevant to the current task. Do not
  redesign what it decides; record any necessary deviation in `DECISIONS.md` with the reason.
- `BUILD_PLAN.md` — the phases. Work on **one phase per session**.
- `PROGRESS.md` — what's done, what's next, known issues. Read it first; update it last.

## Hard rules
- Runtime is offline, CPU-only, 16 GB RAM, Windows 11 without admin/Docker. Code must also run on
  macOS/Linux. One Ollama model loaded at a time.
- Tests run offline with `FakeLLM` and fake embedders. No test may need Ollama, internet, or a
  real template.
- Open-source hygiene: all fixtures synthetic ("Acme Health Plan"). Never add real company,
  client, person or proprietary template content. Never commit `library/`, `workspace/`,
  `templates/*` (except `templates/sample/`), or `config/overrides.yaml`.
- Where the spec says VERIFY, check the real tool (`--help`, installed package source) before coding.
- Dependencies: only those listed in `BUILD_PLAN.md`; ask before adding others.
- No telemetry in project code. Block Ollama cloud models (`:cloud`).

## Commands
- Install dev: `pip install -e .[dev]`
- Lint/format: `ruff check . --fix && ruff format .`
- Test: `pytest -q`
- CLI: `studio --help`, `studio doctor`

## Git workflow
- Branch per phase: `phase/<n>-<slug>` from `main`. Conventional Commits.
- Small commits as you go. Before opening a PR: lint + tests green, `PROGRESS.md` updated.
- Open PRs with `gh pr create`; PR body follows `.github/PULL_REQUEST_TEMPLATE.md` once it exists.

## Style of work
- Be economical: don't print whole files back, don't re-read files you just wrote, keep summaries
  to ~5 lines plus the commands to try.
- Python 3.11+, type hints, pydantic v2, small modules, docstrings on public functions.
