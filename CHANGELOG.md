# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
