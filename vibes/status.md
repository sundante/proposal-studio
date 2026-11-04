# Proposal Studio — Status

_Last updated: 2026-11-04 · Branch `dev` · all 11 phases built · v0.1.0 ready to tag · 199 tests_

Proposal Studio is a fully local, offline proposal workbench: Open WebUI + Ollama + the
`studio` Python package. It turns RFPs into a cited digest and an AI-practice proposal deck
on your own PowerPoint template, answers RFP questions with citations, researches your local
library, and hands file tasks to sandboxed local agents. See [PROJECT_SPEC.md](PROJECT_SPEC.md)
(design), [BUILD_PLAN.md](BUILD_PLAN.md) (phases), [PROGRESS.md](PROGRESS.md) (checklist,
known issues) and [DECISIONS.md](DECISIONS.md) (why).

## At a glance

| Phase | What | Status |
|---|---|---|
| 0 | Bootstrap: repo, OSS files, CI, config, LLM client, guards, CLI | ✅ |
| 1 | Ingest + RAG + `/ask` | ✅ |
| 2 | RFP digest | ✅ |
| 3 | Template inspector + PPTX renderer (no LLM) | ✅ |
| 4 | Blocks, storyline, deck writer | ✅ |
| 5 | Offline research | ✅ |
| 6 | Router core + `studio chat` | ✅ |
| 7 | Open WebUI integration + setup scripts | ✅ |
| 8 | Agents route (`/agent`) | ✅ |
| 9 | Hardening + docs (`studio bench`, full docs) | ✅ |
| 10 | Release pipeline + v0.1.0 | 🟡 prepared — tag after `dev` → `main` |

## Using it now (dev setup)

```bash
scripts/setup.sh                    # once, online (Windows: scripts\setup.ps1)
scripts/start.sh                    # offline from here; open http://localhost:8080
studio owui install --token sk-…    # pipe + agents + PHI filter + / prompts
studio smoke                        # end-to-end check on the real models
```

Then pick **Proposal Studio** in Open WebUI. Typical flow:
`/new` → attach the RFP → ask questions → `/digest xlsx` → `/outline` → `/deck` → `/edit` →
`/render` (download link). Once per library: `/library index`, `/harvest`, then curate
`library/blocks/`. Full guide: [docs/install.md](../docs/install.md); step-by-step walkthrough:
[tutorial.html](../tutorial.html).

## What was built (by area)

- **Foundations:**
  - src-layout package, validated YAML config with runtime overrides (`/config`)
  - Ollama client (schema-constrained output with retries, streaming, single-flight lock)
  - guards (cloud-model block, path sandbox, PHI scan)
  - open-source files
  - CI on Windows and Ubuntu × Python 3.11/3.12, plus a script syntax check and a rendered
    sample-deck artifact
- **RFP:**
  - ingest for PDF/DOCX/XLSX/PPTX/TXT/MD, keeping heading paths, pages/slides and row-wise
    tables
  - PHI block-until-confirmed
  - incremental index (exact NumPy cosine)
  - `/ask` with `[section, p.N]` citations, or "Not found in the RFP."
- **Digest:** map-reduce extraction with citations, de-duplication, requirement ids checked
  against the RFP's own table rows, conflict flags, a Markdown summary and an XLSX matrix.
- **Deck:**
  - `/harvest`: anonymised (twice), edit-protected YAML blocks
  - `/outline`: `include_if` rules that cite the RFP
  - `/deck`: one call per slide over 2–4 vetted blocks, limits enforced in Python, provenance,
    review guards (invented figures/certifications, client claims not in the RFP, filled
    placeholders), skeletons instead of invention
  - `/edit` with a diff and history
- **Render:** your template (`.pptx`/`.potx`) mapped via `layout_map.yaml`, a layered
  architecture diagram, notes with sources, versioned output and a QA report. No LLM.
- **Research:** a plan → multi-query retrieval → cited findings → gap round → synthesis loop,
  with a hard LLM-call cap and a saved markdown report.
- **Router:**
  - every command and alias
  - rules → classifier → clarification
  - file-writing routes wait for `/approve`
  - route line and "Next:" on every reply
  - per-chat sessions
  - `studio chat`
- **Open WebUI:**
  - the Proposal Studio pipe: attachments, confirmation dialog, download links, Valves
  - "Agent · …" models
  - PHI filter and `/` prompts
  - localhost-only API installer
  - `offline.env` (offline, no telemetry, Ollama cloud off, one model loaded)
  - setup/start/smoke scripts for Windows and Unix
- **Agents:** OpenCode and Claude Code (via Ollama's Anthropic API), verified headless; Hermes
  shipped disabled. Plan runs in a throwaway copy → approve → apply → diff → approve copy-back,
  with an isolated HOME, an env allowlist, no shell by default, timeouts and logs.
- **Hardening:**
  - `studio bench [--cpu]`: every budgeted step passes, GPU and CPU-only
  - Open WebUI + studio idle RSS 736 MB
  - worker context 8k
  - docs: README, install, commands (generated), config, templates, agents, performance,
    troubleshooting, privacy, plus **`tutorial.html`**, a detailed single-file offline tutorial
    (a test keeps it in sync with the commands)
- **Release:**
  - allowlisted bundle builder (tracked files only, private-path guard)
  - `release.yml`: sdist + wheel + Windows zip, a clean-install check on Windows, then a GitHub
    Release
  - version 0.1.0 and CHANGELOG prepared

## Problems that real runs caught (all fixed)

- **qwen3:8b output problems** (citations, ids, client claims, `{{date}}` slots):
  - It mis-copied long citation labels. It now cites numbers, and Python adds the labels.
  - It stamped the prompt's example id on every requirement. Ids are now checked against the
    RFP's table rows.
  - It copied a past client's claim onto a client slide, and filled a `{{date}}` slot with the
    due date. Both are now flagged by Python guards.
- **Harvest:** client names leaked into review notes. The notes are now anonymised too.
- **Open WebUI:**
  - FAISS and Open WebUI's torch crashed the server (duplicate OpenMP). Search is now NumPy, and
    FAISS is removed.
  - The confirmation dialog auto-approved when no browser was connected. It now needs a literal
    yes.
- **Agents:** opencode downloads a model catalogue at runtime. That and other fetches are now
  disabled via env vars.

## Still open

- **To release:** promote `dev` → `main`, then `/ship 0.1.0`. That tags `v0.1.0`; CI builds,
  checks the install on Windows, and publishes the release.
- **Not yet run for real:**
  - Windows scripts on a real Windows 11 laptop (CI checks syntax, and the release job does a
    clean install there)
  - the in-browser confirmation dialog and the light-theme step
  - the 16 GB Intel CPU-only target (estimated 2–4× the Mac CPU-only numbers)
  - a visual check of the rendered deck in PowerPoint
- **Quality limits with qwen3:8b:** agents rarely use their file tools; research synthesis isn't
  cited; deck quality depends on curated blocks. See [PROGRESS.md](PROGRESS.md).
- **Hermes Agent:** enable it once a live offline run is verified.
- **Before publishing:** confirm your employment terms allow a personal open-source project in
  this area, and that your firm allows these tools on work machines.

## Phase 11a — Studio UI (2026-11-04)
Open WebUI was too hard to use for this job, so it is being replaced by our own local chat app,
`studio ui`. It needs no new dependencies (Python's built-in web server and a single HTML/JS
page). You drop an RFP on the home screen and a project is created and indexed. You then ask
questions in plain language and get cited answers. **Analyse RFP** and **Build slides** run the
pipeline, and **Download PPTX** saves the deck. A side panel shows the files, the RFP summary
and slide previews. It works in light and dark mode and at phone width. The router now also
accepts commands pasted in code blocks and ingests files sent together with a question. A real
run on qwen3:8b answered "when is it due" in ~10 s and built an 11-slide PPTX in ~75 s. The
Open WebUI build is archived on the `archive/open-webui` branch. Phase 11b removes it from the
repo and rewrites the docs.

## Phase 12 — Workspace folders, layout, models (2026-11-04)
The app now asks, every launch, which **workspace folder** it may work in and requires an
explicit **Trust**, as an editor does. A built-in folder browser is used because native dialogs are
unreliable from a server. Projects, uploads, chats and the library live in that folder, and nothing
outside it is touched. The sidebar collapses to an icon rail, and the right panel can be dragged
wider (up to 75% of the window) or hidden. A **Models** view shows what's installed and loaded,
what fits in RAM, and which model does which job, and lets you reassign them. The security review
finding (the local API had no authentication) is fixed with a per-launch link, plus a header on
writes, and agent commands can no longer be changed from chat. Open WebUI is gone from the repo,
scripts, release job, docs, tutorial and spec. Checked live on qwen3:8b: pick and trust a folder,
then drop the RFP and get a cited answer, with headless-Chrome screenshots in light and dark mode.
Next: Phase 13, the document workbench.

## Phase 12.1 — Projects in folders you choose (2026-11-04)
Feedback: workspaces and projects were two confusing concepts, projects couldn't be deleted, and it
wasn't clear where files went. Now there's one concept. A **project** lives in a folder you pick and
trust when you create it; by default that's a new folder in `Documents/Proposal Studio/` named after
the project. Its path shows in the sidebar and in full in the Files tab, with **Open folder** and
**Copy path**. Each project's **⋯** menu has New chat, Rename, Open folder, Copy path, Remove from
list (files kept) and Delete project and its folder. Settings shows the Proposal Studio folder,
which holds the shared library, and where app settings live. Starting from the home screen asks for
the project name and folder first. Checked live with headless-Chrome screenshots; 213 tests pass.

## Phase 13 — UI rebuild (2026-11-04)
The front end was rebuilt from scratch, still with no build step and no dependencies. It is now
split into small modules, with a warm paper + ink look: serif headings, an ink-blue accent, and
light and dark modes. It has:
- a sidebar that collapses to an icon rail;
- a home screen with a greeting and a project chip on the composer;
- a searchable Projects grid with cards;
- a project page with chats, files, folder and progress;
- a chat view with live status, file cards, a PPTX download card and a resizable panel (Files,
  RFP summary, Slides);
- a full Settings page (theme, folders, models);
- in-app dialogs for every confirm and rename.

The folder chooser is now a Finder-style picker. The New project dialog asks explicitly whether to
create a new folder inside the chosen one, use it as-is, or add an existing project. Checked live on
qwen3:8b, including a full Build slides run, with headless-Chrome screenshots in light, dark and
phone layouts. 215 tests pass.

## Phase 14 — Navigation, composer, models and modes (2026-11-04)
Gaps against the desktop-app reference were closed:
- **Sidebar:** Search (Ctrl/⌘+K) finds projects and chats by any word in the conversation, with
  snippets. Chats can be pinned. The Pinned and Recents sections collapse, and chats with files are
  marked. There are back and forward buttons, and a profile footer with your name, which the home
  screen also uses in its greeting.
- **Composer:** a "+" menu, a **mode** chip (Auto, Ask the RFP, Research, Draft, Chat) and a
  **model** chip with Fast/Thinking. Choices are remembered per chat.
- **Home:** a "Project or folder" picker under the box searches projects, creates one from what you
  type, or adds an existing folder.
- **Temporary chats:** not saved or listed, and deleted when you leave.

Draft and Chat use a new `/chat` route. Draft grounds the reply in the RFP summary and the deck, and
labels it as uncited. Outputs, Templates and Customize have sidebar entries now; their pages are
Phase 15. Voice input was left out because it would send audio off the machine. Checked live on
qwen3:8b (a Draft-mode email, search, pin and the temporary chat). 221 tests pass.

## Phase 15 — Open files in the side panel (2026-11-04)
The RFP can now be read next to the chat. The side panel has a **Document** tab:
- **PDFs** show as real pages. Text can be selected, there's zoom, and find highlights matches.
- **Word, Excel, PowerPoint and text files** show as a clean reading view. It's built from the
  same text that was indexed, so what you read is what the answers are based on.

**Citations open their source.** Clicking a chip such as "4 Requirements, p.3" opens the file at
that page and highlights the passage, or its heading. Attachments in the chat and files on the
project page open the same way.

**Selecting text** pops up Ask about this (quotes it into the message box with file and page),
Copy, and Add to notes. Add to notes copies the passage with its source for now, until the
notebook arrives in Phase 17.

Next: shared drives and co-working (16), then the notebook (17). Checked live on qwen3:8b with
screenshots; 226 tests pass.
