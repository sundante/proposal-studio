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
| 9 | Hardening + docs | ⬜ todo | |
| 10 | Release pipeline + v0.1.0 | ⬜ todo | |

Status values: ⬜ todo · 🟡 in progress · ✅ done

## Current
- Phase in progress: none
- Next step: Phase 9 — Hardening + docs

## Known issues
- Ingesting the same RFP as both PDF and DOCX duplicates excerpts in answers (user-side; the
  docs should recommend one format per document).
- `/digest` takes ~55 s per section group on an Apple-silicon Mac with qwen3:8b; expect several
  minutes per group on the 16 GB CPU-only target. Revisit prompt/output size in Phase 9.
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
