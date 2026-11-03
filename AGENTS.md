# Proposal Studio — notes for coding agents

This is the same guidance as `CLAUDE.md`, for agents other than Claude Code.

- Source of truth: `vibes/PROJECT_SPEC.md` (the decided design), `vibes/BUILD_PLAN.md` (the phases) and
  `vibes/PROGRESS.md` (state; read it first, update it last). Record deviations in `vibes/DECISIONS.md`.
- Runtime: offline, CPU-only, 16 GB RAM, Windows 11 without admin/Docker. Code must also run on
  macOS/Linux. One Ollama model loaded at a time.
- Tests run offline with `tests/fakes.py::FakeLLM` and fake embedders. No Ollama, internet or real
  template.
- Hygiene: synthetic fixtures only ("Acme Health Plan"). Never commit `library/`, `workspace/`,
  `templates/*` (except `templates/sample/`) or `config/overrides.yaml`.
- Dependencies: only those listed in `vibes/BUILD_PLAN.md`.
- No telemetry. Block Ollama cloud models (`:cloud`).
- Commands: `pip install -e .[dev]` · `ruff check . --fix && ruff format .` · `pytest -q` ·
  `studio doctor`.
- Git: commit on `dev` and push `origin dev`. Never touch `main` (promoted manually). No
  branches or PRs. Conventional Commits.
- Python 3.11+, type hints, pydantic v2, small modules, docstrings on public functions.
