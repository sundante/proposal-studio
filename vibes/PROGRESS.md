# Progress

| Phase | Name | Status | Commit |
|---|---|---|---|
| 0 | Bootstrap: repo, OSS foundations, config, LLM client, guards | ✅ done | 3ecd9a8 |
| 1 | Ingest + RAG + /ask | ✅ done | cea14a3 |
| 2 | RFP digest | ✅ done | 72e0a75 |
| 3 | Template inspector + renderer | ✅ done | f68e3e1 |
| 4 | Blocks, storyline, deck writer | ✅ done | cb2b909 |
| 5 | Offline research | ✅ done | 9e1ede5 |
| 6 | Router core | ✅ done | 59b888f |
| 7 | Open WebUI integration + setup scripts | ✅ done | 2b4e1b9 |
| 8 | Agents route | ✅ done | 0761ec7 |
| 9 | Hardening + docs | ✅ done | 6dd79d4 |
| 10 | Release pipeline + v0.1.0 | ⏸ superseded — v0.1.0 (Open WebUI) not shipped | 415d709 |
| 11a | Studio UI: local chat app (`studio ui`) | ✅ done | 0f4b457 |
| 11b | Remove Open WebUI, rewrite docs for the Studio UI | ⬜ todo | |

Status values: ⬜ todo · 🟡 in progress · ✅ done

## Current
- Phase in progress: 11b (remove Open WebUI; docs for the Studio UI)
- Next step: delete `owui/` + `src/studio/owui.py` + `owui-*` CLI commands and the open-webui
  install in `scripts/`; make `start.*` run `studio ui`; rewrite README/install/tutorial/spec.
- Open WebUI build archived on branch `archive/open-webui` (a11c3e6).

## Docs
- User docs: `README.md`, `tutorial.html` (step-by-step, offline single file), `docs/*.md`.
- Project docs: `vibes/` (spec, build plan, decisions, progress, status).

## Known issues
- Studio UI: Stop closes the stream but the model finishes the current step in the background
  (the reply is saved to the chat); a second message in the same project waits for it.
- Studio UI front-end JS has no automated tests (server/API are covered by `tests/test_ui.py`);
  checked by hand with headless Chrome screenshots.
- Ingesting the same RFP as both PDF and DOCX duplicates excerpts in answers (user-side;
  troubleshooting.md and the tutorial recommend one format per document).
- Performance measured with `studio bench` (docs/performance.md); the Intel CPU-only target
  itself is still unmeasured (estimated 2–4× the Mac CPU-only numbers).
- Rendered decks were checked structurally (bounds, overlaps, empty placeholders), not visually:
  no LibreOffice on the dev machine and Quick Look hangs headless. Open the CI `sample-deck`
  artifact in PowerPoint once to eyeball it.
- Deck quality depends on curated blocks: with only 5 synthetic blocks, 4 vendor slides render as
  skeletons. qwen3:8b still imports block claims into client slides and fills `{{date}}` slots;
  both are flagged for review, not prevented.
- `/research` synthesis (summary/implications) is not itself cited and can blur facts; the
  findings carry the citations. Sub-questions from qwen3:8b tend to overlap.
- `setup.ps1`/`start.ps1` are syntax-checked in CI but not yet run on a real Windows 11 laptop.
- The Open WebUI pipe was verified via its HTTP API; the browser confirmation dialog (needs a
  live browser session) and the light-theme step are untested manually.
- If the Ollama tray app is already running, `offline.env`'s `OLLAMA_*` settings don't apply.
- Agent runs with qwen3:8b are slow (30–70 s per step here) and the model often doesn't use its
  file tools; Hermes is disabled until a live offline run is verified.
