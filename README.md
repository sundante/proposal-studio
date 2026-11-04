# Proposal Studio

A fully **local, offline** proposal workbench for pre-sales solutions architects in regulated
industries (US healthcare first). From one chat window it:

- reads an RFP and answers questions about it, citing `[section, p.N]`
- builds a structured digest: problems, requirements, evaluation criteria, compliance, risks
- writes a proposal deck from your own vetted content blocks and renders it onto **your**
  PowerPoint template, with a QA report
- researches across your library of past proposals and reference documents
- hands file tasks to local agent CLIs, sandboxed, with approvals

It all runs on a 16 GB laptop with no admin rights, no Docker and no internet at runtime:
- the **Proposal Studio app** (`studio ui`) is the chat window in your browser;
- [Ollama](https://ollama.com) runs the models;
- the `studio` Python package does the work.

> _Screenshots: coming with the first release._

## Install

1. Download the latest release zip (`proposal-studio-<version>-windows.zip`) from
   [Releases](../../releases), or `git clone` the repo.
2. While online, run setup once. It needs no admin rights and is safe to re-run:
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`
   - macOS/Linux: `scripts/setup.sh`
3. Go offline and start it: `scripts\start.ps1` / `scripts/start.sh`. Your browser opens
   Proposal Studio.
4. Choose a **workspace folder** for your bids and confirm that you trust it. Proposal Studio
   reads and writes only inside it.

The full guide is in [docs/install.md](docs/install.md). Check the install with
`scripts/smoke_test.*`.

> **New here?** The [step-by-step tutorial](vibes/tutorial.html) walks through install, your
> first proposal, building a block library, mapping your own template, research and agents, with
> worked examples. Download it and open it in a browser; it's a single offline file.

## Daily workflow

1. Drop the RFP onto the page. A project is created, and the files are PHI-checked and indexed.
2. Ask anything: "When are proposals due?", "What are the mandatory requirements?" Answers cite
   `[section, p.N]`.
3. **Analyse RFP** builds the digest: problems, requirements, evaluation criteria, compliance
   and risks. It appears in the side panel.
4. **Build slides** writes a tailored deck from your vetted blocks and renders it on your
   template, with a QA report.
5. **Download PPTX** saves the deck. Review it, or revise a slide with
   `/edit platform shorter, mention FHIR R4`, then build again.

To change the layout:
- **Ctrl/⌘+B** collapses the sidebar.
- **Ctrl/⌘+J** toggles the side panel.
- Drag the panel's edge to widen it.
- The model status at the bottom of the sidebar opens the **Models** view: installed models,
  what's loaded, what fits in memory, and which model does what.

Once per library, and whenever it changes:

```
/library index                                  index library/proposals and library/reference
/harvest Old Client Inc                         anonymised reusable blocks → curate library/blocks/*.yaml
/research How have we handled prior authorization before?
```

Commands that write files (`/render`, `/harvest`, `/agent`) never run from plain text without
your confirmation.

## Commands

The full reference is [docs/commands.md](docs/commands.md), generated from `config/routes.yaml`.

| | |
|---|---|
| Opportunities | `/new`, `/use`, `/status` |
| RFP | `/ingest`, `/ask`, `/digest [xlsx] [show]` |
| Deck | `/harvest`, `/blocks`, `/outline`, `/toggle`, `/deck [slide]`, `/edit`, `/render` |
| Research | `/library index\|status`, `/research` |
| Agents | `/agent <name> <task>` (OpenCode, Claude Code via local Ollama) — [docs/agents.md](docs/agents.md) |
| Settings | `/config`, `/config set <key> <value>`, `/config reset` — [docs/config.md](docs/config.md) |

Every command also exists as a CLI (`studio --help`), and `studio chat` gives you the chat in
a terminal.

## Privacy checklist

- [x] Models run in local Ollama only; cloud models are refused.
- [x] The app runs on 127.0.0.1 only, behind a per-launch link, and reads and writes only
      inside the workspace folder you trusted.
- [x] No telemetry in Proposal Studio's code.
- [x] RFPs, the library, workspaces and your templates are gitignored, and the commit hooks
      block them.
- [x] Files are scanned for PHI on ingest; harvested blocks are anonymised and curated by you.
- [ ] You've checked that your organisation allows these tools on your machine.

Details are in [docs/privacy.md](docs/privacy.md).

## Docs

[Tutorial](vibes/tutorial.html) · [Install](docs/install.md) · [Commands](docs/commands.md) · [Configuration](docs/config.md) ·
[Templates](docs/templates.md) · [Agents](docs/agents.md) ·
[Performance](docs/performance.md) · [Troubleshooting](docs/troubleshooting.md) ·
[Privacy](docs/privacy.md)

## Development

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # or: uv venv --python 3.11
.venv/bin/pytest -q              # offline: FakeLLM + fake embedder, no Ollama needed
.venv/bin/ruff check . && .venv/bin/ruff format --check .
studio doctor                    # environment check
studio smoke                     # end-to-end on the real models
studio bench [--cpu]             # performance against the budget
```

The design and its history are in [vibes/](vibes/): `PROJECT_SPEC.md`, `BUILD_PLAN.md`,
`DECISIONS.md`, `PROGRESS.md` and `status.md`. To contribute, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache-2.0](LICENSE)
