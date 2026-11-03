# Contributing

Thanks for helping! Proposal Studio is a local-first tool, and its contributions must keep it that
way.

## Ground rules
- **No real data, ever.** Fixtures are synthetic ("Acme Health Plan", "Example Hospital"). Never
  add real RFPs, client names, people, proposals or proprietary templates.
- **Offline tests.** `pytest` must pass without Ollama, internet or a real template. Use
  `tests/fakes.py::FakeLLM` and the fake embedder.
- **No telemetry** in project code. Cloud models stay blocked.
- Read [PROJECT_SPEC.md](PROJECT_SPEC.md) before larger changes. Record design deviations in
  [DECISIONS.md](DECISIONS.md).

## Workflow
1. Branch from `main` (`feat/<topic>`, `fix/<topic>`, or `phase/<n>-<slug>`).
2. `pip install -e ".[dev]"` and `pre-commit install`.
3. `ruff check . --fix && ruff format . && pytest -q`.
4. Use Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `ci:`).
5. Open a PR and complete the checklist in the template.

## Dependencies
New runtime dependencies need discussion in an issue first. The allowed set is in
[BUILD_PLAN.md](BUILD_PLAN.md).
