# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-04

First release: a fully local, offline proposal workbench on Open WebUI + Ollama.

### Added
- **RFP intake:**
  - ingest for PDF, DOCX, XLSX, PPTX, TXT and MD, keeping heading paths, page/slide numbers
    and row-wise tables
  - PHI scan with confirmation
  - incremental per-opportunity index
  - `/ask` with `[section, p.N]` citations, or "Not found in the RFP."
- **`/digest`:** a map-reduce RFP digest of problems, before/after, requirements (ids verified
  against the RFP), evaluation criteria, compliance, systems, risks and open questions, with
  citations, de-duplication and conflict flags. Includes a Markdown summary and an XLSX
  requirements matrix.
- **Deck:**
  - `/harvest` builds anonymised, human-curated blocks from past proposals (edit-protected,
    incremental)
  - `/outline` uses `include_if` storyline rules and persistent `/toggle` choices
  - `/deck` tailors vetted blocks to the digest, with provenance, limit enforcement and review
    flags for unsupported claims
  - `/edit` shows a before/after diff and keeps a deck history
- **`/render`:** deck → versioned PPTX on *your* template (`.pptx`/`.potx`) with no LLM. Includes
  `studio template inspect`, a layered architecture diagram, sources in the speaker notes, a QA
  report, and an original neutral sample template.
- **`/research`:** offline multi-step research over the library and the active RFP, with cited
  findings, one gap round and a hard LLM-call cap. Plus `studio library index|status`.
- **`/agent`:** sandboxed local agent CLIs (OpenCode, and Claude Code via local Ollama; Hermes
  shipped disabled). Each run plans in a throwaway copy, then approve → apply → diff → approve
  copy-back, with an isolated HOME and an env allowlist.
- **Chat router:**
  - every command and alias
  - auto-routing: rules, then the classifier, then a clarifying question
  - confirmation before file-writing routes
  - a route status line and "Next:" hints on every reply
  - per-chat sessions
  - `studio chat` REPL
- **Open WebUI integration:**
  - the **Proposal Studio** pipe: attachments, confirmation dialog, download links, Valves
  - "Agent · …" models
  - PHI warning filter
  - slash-command prompts
  - `studio owui install`
- **Setup:** `scripts/setup|start|smoke_test` for Windows (no admin) and macOS/Linux, sharing one
  offline, no-telemetry environment (`scripts/offline.env`).
- **Tools:** `studio doctor`, `studio smoke` and `studio bench` (performance against the budget).
- **Docs:** install, commands, configuration, templates, agents, performance, troubleshooting and
  privacy.
- **Open-source foundations:** Apache-2.0, contributing guide, code of conduct, security policy,
  issue/PR templates, Dependabot, pre-commit with a private-path guard, CI on Windows and Ubuntu
  (Python 3.11/3.12), and a release workflow (sdist, wheel, Windows bundle zip, install check on
  Windows).

### Notes
- Vector search is exact cosine similarity with NumPy: FAISS and Open WebUI's torch crash
  together on duplicate OpenMP runtimes.
- Tested with Open WebUI 0.13.0, Ollama 0.40, and qwen3:8b / qwen3:4b / nomic-embed-text.

[Unreleased]: https://github.com/sundante/proposal-studio/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sundante/proposal-studio/releases/tag/v0.1.0
