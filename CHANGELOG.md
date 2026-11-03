# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `/harvest`: reusable, anonymised blocks from past proposals (`library/blocks/*.yaml`), with
  edit protection, incremental re-harvest and review flags; `/blocks` list/search.
- `/outline` with `include_if` rules over the digest and persistent `/toggle` choices.
- `/deck` (all or one slide) tailoring vetted blocks to the digest with provenance, limit
  enforcement and review flags for unsupported claims; `/edit` with a before/after diff and
  deck history.
- `/render`: deck.json → versioned PPTX on your template (no LLM), with layout/placeholder
  mapping in `config/layout_map.yaml`, limit enforcement, layered architecture diagram, speaker
  notes with sources, and a QA report. `.potx` templates supported.
- `studio template inspect` (layouts + placeholders → `.layouts.json`) and `studio template
  sample`; an original neutral sample template in `templates/sample/`.
- Slide schemas for all 11 storyline slide types; CI job uploading the rendered sample deck.
- `/digest`: map-reduce RFP digest (`digest.json`) with cited problems, before/after,
  requirements, evaluation criteria, compliance, systems, risks and open questions;
  de-duplication, verified requirement ids, conflict flags; Markdown summary; optional XLSX
  requirements matrix (`studio digest --xlsx`); stale-digest detection in `status`.
- Ingest for PDF, DOCX, XLSX, PPTX, TXT and MD with heading paths, page/slide numbers and
  row-wise tables; section-aware chunking; PHI warning with confirmation.
- Per-opportunity FAISS index with incremental updates (file hashing) and library collections.
- `/ask` answers with `[section, p.N]` citations, or "Not found in the RFP."
- Opportunities and per-chat sessions under `workspace/`.
- CLI: `studio new|use|ingest|ask|status`.
- Project scaffold (src layout, `studio` package, `pyproject.toml`, ruff and pytest config).
- Open-source foundations: Apache-2.0 licence, contributing guide, code of conduct, security
  policy, issue and PR templates, Dependabot, pre-commit with a private-path guard.
- CI on Windows and Ubuntu with Python 3.11 and 3.12.
- Default config (`config/*.yaml`) with pydantic validation, plus `config/overrides.yaml` for
  runtime changes.
- Ollama client with schema-constrained output, retries, streaming, batched embeddings and a
  single-flight lock.
- Guards: cloud-model block, path sandbox, PHI scan.
- CLI: `studio --version`, `studio config show|set|reset`, `studio doctor`.
