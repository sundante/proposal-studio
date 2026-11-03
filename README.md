# Proposal Studio

> **Under construction.** Pre-release; see [vibes/PROGRESS.md](vibes/PROGRESS.md) for build status.

A fully **local, offline** proposal workbench for pre-sales solutions architects in regulated
industries. It turns RFP documents into a proposal deck on your own PowerPoint template, answers
questions about an RFP with citations, and researches over a local reference library. Everything
runs from one chat UI, [Open WebUI](https://github.com/open-webui/open-webui), backed by local
models in [Ollama](https://ollama.com).

- Nothing leaves the machine: no telemetry, cloud models blocked.
- Runs on a 16 GB CPU-only laptop, with no admin rights and no Docker.
- Deterministic Python routing. LLMs only do narrow, schema-constrained jobs. Formatting never
  goes through an LLM.

## Install

See [docs/install.md](docs/install.md): run `scripts/setup` once while online, then
`scripts/start` and open http://localhost:8080 (pick the **Proposal Studio** model).

## Development

```bash
python -m venv .venv            # Python 3.11+
.venv/bin/pip install -e ".[dev]"   # Windows: .venv\Scripts\pip
pytest -q
studio --help
studio doctor
```

Design: [vibes/PROJECT_SPEC.md](vibes/PROJECT_SPEC.md) · Plan: [vibes/BUILD_PLAN.md](vibes/BUILD_PLAN.md) ·
Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)

## License

[Apache-2.0](LICENSE)
