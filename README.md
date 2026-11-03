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
[Open WebUI](https://github.com/open-webui/open-webui) as the chat UI,
[Ollama](https://ollama.com) for the models, and the `studio` Python package for the work.

> _Screenshots: coming with the first release._

## Install

1. Download the latest release zip (`proposal-studio-<version>-windows.zip`) from
   [Releases](../../releases), or `git clone` the repo.
2. While online, run setup once. It needs no admin rights and is safe to re-run:
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`
   - macOS/Linux: `scripts/setup.sh`
3. Go offline and start it: `scripts\start.ps1` / `scripts/start.sh`. Open
   http://localhost:8080 and create the local admin account.
4. Add Proposal Studio to Open WebUI: `studio owui install --token <API key>`, or paste the
   files from `owui/` by hand.

The full guide is in [docs/install.md](docs/install.md). Check the install with
`scripts/smoke_test.*`.

> **New here?** The [step-by-step tutorial](tutorial.html) walks through install, your first
> proposal, building a block library, mapping your own template, research and agents, with
> worked examples. Download it and open it in a browser; it's a single offline file. To read it
> online, enable GitHub Pages for the repo (Settings → Pages → branch `main`, folder `/`), then open
> `<pages-url>/tutorial.html`.

## Daily workflow

Pick the **Proposal Studio** model and:

```
/new acme-2026 Acme Health Plan AI platform     create an opportunity
(attach the RFP files)                          → /ingest  (PHI check, indexing)
When are proposals due?                         → /ask     (cited answer)
/digest xlsx                                    problems, requirements, criteria, compliance, risks
/outline                                        which storyline slides, and why
/deck                                           tailored deck.json from your vetted blocks
/edit platform shorter, mention FHIR R4         revise one slide (shows a diff)
/render                                         PPTX on your template + QA report + download link
```

Once per library, and whenever it changes:

```
/library index                                  index library/proposals and library/reference
/harvest Old Client Inc                         anonymised reusable blocks → curate library/blocks/*.yaml
/research How have we handled prior authorization before?
```

Plain text works too. Every reply starts with `→ routed to /x (rules | classifier | command)`.
Commands that write files (`/render`, `/harvest`, `/agent`) never run without your confirmation.

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
- [x] Open WebUI runs in offline mode on 127.0.0.1: no web search, sharing, telemetry or update
      checks.
- [x] No telemetry in Proposal Studio's code.
- [x] RFPs, the library, workspaces, your templates and Open WebUI's data are gitignored, and
      the commit hooks block them.
- [x] Files are scanned for PHI on ingest; harvested blocks are anonymised and curated by you.
- [ ] You've checked that your organisation allows these tools on your machine.

Details are in [docs/privacy.md](docs/privacy.md).

## Docs

[Tutorial](tutorial.html) · [Install](docs/install.md) · [Commands](docs/commands.md) · [Configuration](docs/config.md) ·
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
