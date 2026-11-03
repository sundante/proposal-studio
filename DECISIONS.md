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
