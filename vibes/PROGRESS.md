# Progress

| Phase | Name | Status | Commit |
|---|---|---|---|
| 0 | Bootstrap: repo, OSS foundations, config, LLM client, guards | ✅ done | 3ecd9a8 |
| 1 | Ingest + RAG + /ask | ✅ done | cea14a3 |
| 2 | RFP digest | ✅ done | 72e0a75 |
| 3 | Template inspector + renderer | ✅ done | f68e3e1 |
| 4 | Blocks, storyline, deck writer | ✅ done | cb2b909 |
| 5 | Offline research | ✅ done | 9e1ede5 |
| 6 | Router core | ⬜ todo | |
| 7 | Open WebUI integration + setup scripts | ⬜ todo | |
| 8 | Agents route | ⬜ todo | |
| 9 | Hardening + docs | ⬜ todo | |
| 10 | Release pipeline + v0.1.0 | ⬜ todo | |

Status values: ⬜ todo · 🟡 in progress · ✅ done

## Current
- Phase in progress: none
- Next step: Phase 6 — Router core

## Known issues
- Ollama keeps the embed model and worker loaded together unless `OLLAMA_MAX_LOADED_MODELS=1`
  is set (done by `start.ps1`/`start.sh` in Phase 7).
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
