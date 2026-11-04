# Proposal Studio — Build Plan

Phases are built one per Claude Code session with `/phase <n>`. Each phase ends with commits pushed to `dev`.

> **Note (2026-11-04):** GitHub Actions (CI, release), Dependabot, the `.github/` templates and the
> community/agent docs (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, AGENTS.md, START_HERE.md,
> docs/performance.md) were removed; checks run locally with `/verify` and releases are built
> locally by `/ship`. Phase descriptions below are kept as history.
>
> **Status (2026-11-04):** all phases 0–10 are built. v0.1.0 is prepared; the tag is created
> with `/ship 0.1.0` after `dev` is promoted to `main`. Deviations are in `vibes/DECISIONS.md`;
> remaining known issues are in `vibes/PROGRESS.md`.
The design is in `vibes/PROJECT_SPEC.md`; progress is tracked in `vibes/PROGRESS.md`.

## Allowed dependencies
Runtime: `httpx`, `pydantic>=2`, `pyyaml`, `pymupdf`, `python-docx`, `openpyxl`, `python-pptx`,
`numpy`, `typer`. (`faiss-cpu` was dropped in Phase 7: see DECISIONS.md.)
Dev (`[dev]` extra): `pytest`, `pytest-asyncio`, `ruff`, `pre-commit`, `build`.
(`open-webui` was installed alongside until Phase 12; it is no longer used.)
Optional, only if Phase 5 records a reason in vibes/DECISIONS.md: `langgraph`.
Anything else → ask first.

---

## Phase 0 — Bootstrap: repo, OSS foundations, config, LLM client, guards
Spec: §0, §3, §4, §6, §7 (PHI scan only), §16.1, §16.2
- Repo layout from §3 (empty modules with docstrings), `pyproject.toml` (package `studio`, src layout,
  Python ≥3.11, entry point `studio = studio.cli:app`, `[dev]` extra, ruff config), `.gitignore` per §16.1.
- OSS files per §16.1: LICENSE (Apache-2.0), README (short placeholder with project pitch + "under
  construction"), CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG, `.github/` issue + PR templates,
  `dependabot.yml`, `.pre-commit-config.yaml` with the library/workspace commit guard. `AGENTS.md` =
  copy of the essentials of `CLAUDE.md` for other agents.
- CI `.github/workflows/ci.yml` per §16.2 (the render-artifact job is added in Phase 3).
- `config/*.yaml` defaults from §4, §5, §9.2, §10.1; `studio/config.py` (pydantic models, base +
  `overrides.yaml`, validation, set/reset helpers for `/config`).
- `studio/llm.py` per §6 (+ `FakeLLM` in `tests/fakes.py`); `studio/guards.py` (cloud-model block, path
  sandbox, PHI regex scan).
- `studio/cli.py`: `studio --version`, `studio config show|set|reset`, `studio doctor` (Ollama reachable,
  models pulled, Python version, workspace writable — printed as a checklist).
- Tests: config validation, cloud-model rejection, sandbox traversal, PHI scan, FakeLLM structured retry.
- Done when: CI green on Windows + Ubuntu.

## Phase 1 — Ingest + RAG + `/ask`
Spec: §7
- `ingest.py`: PDF/DOCX/XLSX/PPTX/TXT/MD → sections with heading path + page/slide; tables row-wise
  with headers; section-aware chunking (~800 tokens, 100 overlap); file hashing.
- `rag.py`: vector index per opportunity and per library collection; incremental updates; `retrieve(top_k)`;
  `answer()` with mandatory `[section, p.N]` citations and an explicit "not found in the RFP" path.
- `session.py`: opportunities (create/use/list) + per-chat state in `workspace/.sessions/`.
- CLI: `studio new|use|ingest|ask|status`.
- Synthetic "Acme Health Plan" RFP fixtures generated in test setup (PDF + DOCX). Tests: chunk metadata,
  incremental indexing, citation format (FakeLLM + deterministic fake embedder).

## Phase 2 — RFP digest
Spec: §8
- Pydantic `Digest` exactly as §8 (`cite = {section, page}`).
- Map: schema-constrained extraction per section group (<2k tokens of RFP text per call). Reduce in
  Python: merge, de-duplicate (normalised text + embedding similarity), keep all citations.
- Markdown summary renderer for chat; optional XLSX compliance matrix.
- CLI: `studio digest [--xlsx]`. Tests: canned section outputs → valid, de-duplicated digest.

## Phase 3 — Template inspector + renderer (no LLM)
Spec: §9.3, §9.5, §16.2 (render artifact job)
- `deck/schemas.py`: pydantic model per slide type in the §9.2 spine, char limits from
  `layout_map.yaml`, `speaker_notes` + `sources` on every slide; `Deck` model.
- `render/inspect_template.py` + `studio template inspect <file>` → `templates/<name>.layouts.json`.
- `.potx` support per §9.5 (try the content-type patch; record the outcome in vibes/DECISIONS.md).
- `render/renderer.py`: layouts/placeholders via `layout_map.yaml`, remove sample slides, shape-drawn
  layered architecture slide, versioned output, QA report.
- Original neutral light template generated in code under `templates/sample/` + matching `layout_map.yaml`.
- `studio render [--deck path]`; sample `deck.json` fixture renders with zero QA errors.
- Add the CI job that renders the fixture and uploads the PPTX artifact.

## Phase 4 — Blocks, storyline, deck writer
Spec: §9.1, §9.2, §9.4
- `blocks.py`: `/harvest` over `library/proposals` (PPTX slides, DOCX/PDF sections) → classify by
  slide type, extract client-neutral blocks, anonymise with `{{client}}`, flag uncertain items, YAML
  per block, never overwrite `edited: true`; search by tags + embeddings.
- `deck/storyline.py`: `outline.json` from `storyline.yaml` + digest (`include_if` rules), toggles.
- `deck/writer.py`: 2–4 blocks per slide, tailoring prompt with the no-invention rule, schema output,
  one shorten retry, safe truncation + flag, provenance; single-slide regenerate; `/edit` with diff.
- CLI: `studio harvest|blocks|outline|toggle|deck|edit`. Tests: anonymisation, edited-block
  protection, `include_if`, writer truncation path.

## Phase 5 — Offline research
Spec: §11
- `research.py` as a small explicit loop (LangGraph only with a recorded reason): decompose →
  multi-query retrieval over library + active RFP → cited findings → one gap round → synthesis →
  markdown report saved. Hard LLM-call cap; progress callback.
- `studio research "<q>"`. Tests: call cap, citation format.

## Phase 6 — Router core
Spec: §5
- `router.py`: all §5.1 commands + aliases, dispatch to phases 1–5, auto-routing (rules → classifier
  → clarification below threshold), file-writing routes never auto-run without confirmation,
  "→ routed to …" status line, "Next:" suggestions.
- Single entry point `handle(message, attachments, session, emit)` → async iterator of chunks.
- `studio chat` REPL over `handle()`.
- Tests: every command parses, aliases, rules routing, low confidence → clarification,
  auto-routed `/render` requires confirmation.

## Phase 7 — Open WebUI integration + setup scripts
Spec: §12, §16.4
- VERIFY first, against the installed `open-webui` package in a scratch venv (source/docs): Pipe and
  Filter structure, Valves/UserValves, `__event_emitter__` status, `__event_call__` confirmation,
  how attached files reach a pipe, how to return a downloadable file, Prompt import JSON format,
  offline/telemetry/RAG env var names. Record in vibes/DECISIONS.md before coding.
- `owui/router_pipe.py`, `owui/phi_filter.py`, `owui/prompts/*.json`.
- `scripts/setup.ps1` (idempotent, no admin), `scripts/start.ps1` (env from §12.2), `scripts/smoke_test.ps1`
  (doctor + synthetic RFP through ingest → digest → outline → deck → render on the sample template).
  Also provide `setup.sh`/`start.sh` equivalents for macOS/Linux dev.
- `docs/install.md` (Open WebUI functions, prompt import, Valves, light theme).

## Phase 8 — Agents route
Spec: §10
- VERIFY each CLI's headless flags with `--help` (opencode, claude, hermes); update
  `config/agents.yaml`; mark any CLI without a reliable headless mode as unsupported with a clear
  message. Record in vibes/DECISIONS.md.
- `studio/agents/`: config-driven adapters, sandbox (copy-in, copy-back on approval, path checks,
  env allowlist), plan → approve → apply, streaming, timeouts + cancel, logs, changed-file diff,
  Windows `.cmd` shim resolution.
- `owui/agents_pipe.py` (manifold), `/agent` in the router, `studio agent <name> "<task>"`.
- Tests with a fake agent CLI script: plan/apply, rejection, timeout, sandbox escape, env stripping.

## Phase 9 — Hardening + docs
Spec: §14, §15
- Check every route against the performance budget; trim prompts/`num_ctx`; `think=false` default;
  one model loaded at a time.
- Full README (pitch, screenshots placeholder, install from Releases, daily workflow
  `/new → /ingest → /digest → /outline → /deck → /render`, command reference, privacy checklist) and
  `docs/` pages: commands, config, templates (how to map your own template), agents, troubleshooting,
  privacy.

## Phase 10 — Release pipeline + v0.1.0
Spec: §16.3, §16.4
- `.github/workflows/release.yml`: on tag `v*.*.*` build sdist + wheel + `proposal-studio-<ver>-windows.zip`,
  create a GitHub Release with notes from CHANGELOG.
- Verify the zip installs cleanly in a fresh folder with `setup.ps1` (simulate on the CI Windows runner).
- Then run `/ship 0.1.0`.

## Phase 11 — Studio UI (replaces Open WebUI)
Spec: §1, §2, §5, §12 (deviation recorded in DECISIONS.md, 2026-11-04)
- **11a (done):** `studio ui` — stdlib local server + single-page chat app (`src/studio/ui/`):
  projects/chats sidebar, drag-and-drop upload → ingest, streamed answers with citations,
  Analyse RFP / Build slides / Download PPTX, side panel (Files, RFP summary, Slides).
  Router: fenced commands parse, files + text = ingest then route, clearer `/use` and `/ingest`
  errors. Tests: `tests/test_ui.py` (real HTTP, FakeLLM).
- **11b (done in Phase 12):** remove `owui/`, `src/studio/owui.py`, the `owui-*` CLI commands and the open-webui
  install from `setup.*`/`start.*`/`offline.env`/`build_release.py`/release workflow;
  `start.*` launch `studio ui`. Rewrite README, `docs/install.md`, the tutorial and spec §1/2/5/12
  for the Studio UI; drop `open-webui` from the dependency notes.

## Phase 12 — Workspace, trust, panels, models list (+ 11b cleanup, security fix)
Spec: §1, §2, §4.2, §12 (as updated)
- App root vs data root: `RouterContext.app_root` (config, templates) vs `root` (trusted workspace:
  `projects/`, `library/`, `.studio/`); `session.workspace_dir` returns `projects/` in a workspace.
- `studio.trust`: per-user registry of trusted folders; refuses drives, home, system folders.
- Server: active workspace (409 until trusted), `/api/workspace`, `/api/fs` folder browser,
  `/api/models` (pulled, loaded, roles, fits-in-RAM), role assignment; per-launch token cookie +
  `X-Studio` header for writes; chat `/config set agents.*` refused.
- UI: workspace picker + trust dialog + switcher; collapsible sidebar (icon rail, Ctrl/⌘+B);
  resizable/collapsible right panel (drag, double-click, Ctrl/⌘+J); Models view.
- Remove Open WebUI everywhere (code, scripts, release job, docs, tutorial, spec).

## Phase 13 — UI rebuild (done)
- Front end rewritten from scratch as ES modules (no build step, no dependencies):
  `static/{index.html, css/{tokens,base,components,layout}.css, js/{main,api,state,dom,markdown,
  actions}.js, js/ui/, js/views/, js/panels/, js/dialogs/}`.
- Warm paper + ink design system (serif headings, ink-blue accent, light/dark); desktop-app layout
  with sidebar (rail), home with project chip, Projects grid, project page, chat with side panel,
  Settings page; in-app dialogs/menus/toasts (no browser confirm/prompt).
- Finder-style folder picker (places, breadcrumbs, select vs open, new folder) and a New project
  dialog with explicit "new folder inside / use this folder / add existing project" choices.
- Server: static sub-folders with explicit MIME types; `/api/fs` returns places; projects have a
  description.

## Phase 14 — Navigation, composer, models and modes (done)
- Sidebar: Search (Ctrl/⌘+K, `/api/search`), Outputs/Templates/Customize links, collapsible
  Pinned + Recents, file marker, back/forward, profile footer (name in `settings.json`).
- Composer: "+" menu, mode chip (Auto · Ask the RFP · Research · Draft · Chat), model chip with
  Fast/Thinking; choices stored per chat (`Chat.prefs`) and applied with a per-message LLM factory.
- New `/chat` route (free conversation with history; Draft mode adds project context, and
  `<slide_id> <instruction>` edits that slide). Temporary chats (not listed, purged).

## Phase 15 — Open files in the side panel (done)
- `src/studio/ui/docview.py`: PDF page PNGs (pymupdf, cached per page/width in
  `<project>/.studio-cache/`), word boxes for a selectable text layer, find with rects; reading
  view for DOCX/XLSX/PPTX/TXT/MD via `ingest.extract_sections`; raw download and open in the
  default app.
- Citations are clickable: `rag.answer(on_hits=)` → `h_ask` stores sources → SSE `sources` →
  saved on the message; chips open the file at the cited page and highlight the passage (or its
  section heading).
- Document tab in the side panel (also from the project page): file switcher, zoom, find,
  selection toolbar (Ask about this, Copy, Add to notes → Phase 17).

## Phase 16 — Shared drives and co-working
- Sync-folder places (Google Drive for desktop, OneDrive/SharePoint, network drives), import with
  linked origins, presence, work lock, per-person chats, conflict-copy detection.

## Phase 17 — Notebook (sources + notes)
- Notes (answers, passages, own notes) with citations, indexed for answers; Generate briefing /
  FAQ / win themes / exec summary from selected notes; export to Markdown and Word.

## Phase 18 — Outputs, Templates and Customize
- See the approved plan: outputs gallery + home strip; templates (upload, inspect, set active,
  slide-type → layout mapping with test render); customize (storyline, content blocks, routing,
  library).

## Phase 15b — (merged into Phase 15) Document workbench details
- Document tab in the side panel: PDF pages rendered by pymupdf with a selectable text layer;
  DOCX/XLSX/PPTX/TXT reading view from `ingest.extract_sections`; find in document.
- Citations open the source: `rag.answer(on_hits=…)` → SSE `sources` → chip click jumps to the
  page and highlights the passage.
- Select text → Ask about this / Explain / Add to notes / Research this.

## Phase 19 — Research in the workbench + opt-in web (notes → Phase 17 notebook)
- `projects/<id>/notes.md` edited in a Notes tab, autosaved, snapshotted before appends, and indexed
  so answers can cite it; "Add to notes" on replies, selections and research results.
- Research tab over RFP / notes / library, with **opt-in** web search (`studio.web`, off by
  default, PHI-checked query only, every request logged in `.studio/web-log.jsonl`; VERIFY the
  provider first). Records a deviation from the offline rule in DECISIONS.md.

## Phase 20 — Model router and suggestions
- `config/model_catalog.yaml` + `studio.modelrouter`: task per command → best pulled model that
  fits RAM, preferring the loaded one; suggestion chip in the composer; per-chat role overrides
  (never switches automatically).
