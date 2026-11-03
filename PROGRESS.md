# Progress

| Phase | Name | Status | PR |
|---|---|---|---|
| 0 | Bootstrap: repo, OSS foundations, config, LLM client, guards | ✅ done (pending CI) | phase/0-bootstrap |
| 1 | Ingest + RAG + /ask | ⬜ todo | |
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
- Phase in progress: none (Phase 0 awaiting PR merge + green CI on Windows/Ubuntu)
- Next step: Phase 1 — Ingest + RAG + /ask

## Known issues
- Remote push/PR needs `gh auth login` on the dev machine.
- Dev machine has no models pulled: `ollama pull qwen3:8b qwen3:4b nomic-embed-text`.
- CI on Windows not yet observed; first PR run is the Phase 0 done check.
