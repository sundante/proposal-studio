# Progress

| Phase | Name | Status | Commit |
|---|---|---|---|
| 0 | Bootstrap: repo, OSS foundations, config, LLM client, guards | ✅ done | 3ecd9a8 |
| 1 | Ingest + RAG + /ask | ✅ done | cea14a3 |
| 2 | RFP digest | ✅ done | 72e0a75 |
| 3 | Template inspector + renderer | ✅ done | f68e3e1 |
| 4 | Blocks, storyline, deck writer | ⬜ todo | |
| 5 | Offline research | ⬜ todo | |
| 6 | Router core | ⬜ todo | |
| 7 | Open WebUI integration + setup scripts | ⬜ todo | |
| 8 | Agents route | ⬜ todo | |
| 9 | Hardening + docs | ⬜ todo | |
| 10 | Release pipeline + v0.1.0 | ⬜ todo | |

Status values: ⬜ todo · 🟡 in progress · ✅ done

## Current
- Phase in progress: none
- Next step: Phase 4 — Blocks, storyline, deck writer

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
