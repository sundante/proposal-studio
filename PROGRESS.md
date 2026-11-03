# Progress

| Phase | Name | Status | PR |
|---|---|---|---|
| 0 | Bootstrap: repo, OSS foundations, config, LLM client, guards | ✅ done | phase/0-bootstrap |
| 1 | Ingest + RAG + /ask | ✅ done (pending CI) | phase/1-ingest-rag |
| 2 | RFP digest | ⬜ todo | |
| 3 | Template inspector + renderer | ⬜ todo | |
| 4 | Blocks, storyline, deck writer | ⬜ todo | |
| 5 | Offline research | ⬜ todo | |
| 6 | Router core | ⬜ todo | |
| 7 | Open WebUI integration + setup scripts | ⬜ todo | |
| 8 | Agents route | ⬜ todo | |
| 9 | Hardening + docs | ⬜ todo | |
| 10 | Release pipeline + v0.1.0 | ⬜ todo | |

Status values: ⬜ todo · 🟡 in progress · ✅ done

## Current
- Phase in progress: none (Phase 1 awaiting PR merge + green CI)
- Next step: Phase 2 — RFP digest

## Known issues
- `gh` is not authenticated on the dev machine; PRs are opened from the GitHub compare page.
- Ollama keeps the embed model and worker loaded together unless `OLLAMA_MAX_LOADED_MODELS=1`
  is set (done by `start.ps1`/`start.sh` in Phase 7).
- Ingesting the same RFP as both PDF and DOCX duplicates excerpts in answers (user-side; the
  docs should recommend one format per document).
