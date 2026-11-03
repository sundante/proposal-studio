# Decisions log

Append-only. One entry per decision or deviation from `PROJECT_SPEC.md`.

Format:
```
## YYYY-MM-DD — <short title>  (Phase N)
- Context:
- Decision:
- Why:
- Spec impact: (section + what changed, or "none")
```

## 2026-11-03 — Foundational decisions  (pre-build)
- Context: Planning session.
- Decision: Fully local + offline runtime; Open WebUI as UI; deterministic Python router with
  slash commands + auto-routing; agent CLIs (Claude Code, OpenCode, Hermes Agent) called headlessly
  in a sandbox with two-phase approval; offline research over a local library; decks built from
  harvested, anonymised blocks on a fixed storyline; renderer uses the user's own template and no
  LLM; open-source on GitHub under Apache-2.0, installed from Releases.
- Why: 16 GB CPU-only target, no admin/Docker, US-healthcare data constraints, reproducible
  formatting, public distribution.
- Spec impact: none (this is the baseline).

## 2026-11-03 — Pre-build ambiguity resolutions  (kickoff)
- Context: Kickoff review of PROJECT_SPEC.md before Phase 0.
- Decision:
  1. Dev Python: uv-managed 3.11 venv (`uv venv --python 3.11 .venv`). CI covers 3.11 + 3.12.
     3.11 is preferred at runtime because Open WebUI shares the venv.
  2. Token counts for chunking (~800 tokens / 100 overlap) are approximated as `len(text) / 4`.
     No tokenizer dependency.
  3. LLM access goes through an `LLMClient` Protocol in `studio/llm.py`. Modules receive the client
     as a parameter; `OllamaClient` is the real implementation, `tests/fakes.py::FakeLLM` the fake.
  4. Shared `Cite {section, page}` and similar cross-module models live in `studio/models.py`.
  5. `/config set` takes dotted paths into the config model; `<role>.<field>` is shorthand for
     `roles.<role>.<field>`. Overrides are deep-merged from `config/overrides.yaml`, validated with
     `extra="forbid"`.
  6. Project root discovery: env var `STUDIO_HOME`, else the current working directory. `config/`,
     `workspace/`, `library/`, `templates/` resolve against it.
  7. Structured output relies on Ollama's JSON-schema `format` (Ollama >= 0.5); `studio doctor`
     reports the Ollama version from `/api/version`.
  8. Single-flight generation lock is a process-wide `threading.Lock` with an `on_wait` status
     callback, usable from the sync CLI and from the async pipe (via a worker thread).
- Why: Removes guesswork that would otherwise change the shape of Phases 0–3.
- Spec impact: §3 adds `src/studio/models.py`; §6 notes the `LLMClient` Protocol.

## 2026-11-03 — Known environment risks  (kickoff)
- Context: Target is Windows 11, 16 GB, CPU-only, no admin.
- Decision: Track, don't block:
  - `pip install open-webui` pulls torch + sentence-transformers (multi-GB); the <2 GB idle RAM
    budget (§15) is at risk. Revisit in Phase 9 (e.g., embeddings via Ollama, lazy imports).
  - Hermes Agent may lack a native Windows/headless mode; expect "unsupported headless" in Phase 8.
- Why: Visibility for later phases.
- Spec impact: none.
