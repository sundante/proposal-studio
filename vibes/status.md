# Proposal Studio — Status

_Last updated: 2026-11-04 · Branch `dev` · Phases 0–15 built · 226 tests · no CI (checks run locally)_

Proposal Studio is a fully local, offline proposal workbench:
- the **Proposal Studio app** (`studio ui`) is a browser app served from your own machine;
- **Ollama** runs the models;
- the **`studio`** Python package does the work.

It turns RFPs into a cited summary and a proposal deck on your own PowerPoint template, answers
RFP questions with clickable citations, lets you read the RFP beside the chat, researches your
local library, and hands file tasks to sandboxed local agents.

See [PROJECT_SPEC.md](PROJECT_SPEC.md) (design), [BUILD_PLAN.md](BUILD_PLAN.md) (phases),
[PROGRESS.md](PROGRESS.md) (checklist, known issues) and [DECISIONS.md](DECISIONS.md) (why).

## At a glance

| Phase | What | Status |
|---|---|---|
| 0–6 | Engine: config, LLM client, guards, ingest + RAG, digest, renderer, deck writer, research, router | ✅ |
| 7–10 | Open WebUI front end, agents, hardening, release pipeline | ✅ built, then replaced (archived on `archive/open-webui`) |
| 11–13 | Proposal Studio app: local server, projects in trusted folders, full UI rebuild | ✅ |
| 14 | Search, pinned/temporary chats, modes (Auto · Ask · Research · Draft · Chat), model + Fast/Thinking | ✅ |
| 15 | Read files in the side panel; citations open the cited page | ✅ |
| 16 | Shared drives and co-working | ⬜ next |
| 17 | Notebook (sources + notes) | ⬜ |
| 18 | Outputs, Templates, Customize pages | ⬜ |
| 19 | Research in the workbench + opt-in web | ⬜ |
| 20 | Model-router suggestions | ⬜ |

## Using it now

```bash
scripts/setup.sh          # once, online (Windows: scripts\setup.ps1)
scripts/start.sh          # offline from here; opens the app in your browser
studio smoke              # optional end-to-end check on the real models
```

In the app:
1. **New project.** Name it and choose its folder: the default is
   `Documents/Proposal Studio/<name>`, or any folder you trust.
2. Drop the RFP onto the chat and ask questions. Citation chips open the PDF at the cited page.
3. **Analyse RFP** builds the summary; **Build slides** writes and renders the deck;
   **Download PPTX** saves it.
4. Use the composer chips to switch mode or model. Use Search (Ctrl/⌘+K), and pin the chats you
   want to keep at the top.

Full guide: [docs/install.md](../docs/install.md); walkthrough: [tutorial.html](tutorial.html).

## What was built (by area)

- **Engine:**
  - validated YAML config with overrides;
  - Ollama client (schema-constrained output, streaming, one generation at a time);
  - guards: cloud models blocked, path sandbox, PHI scan;
  - ingest for PDF/DOCX/XLSX/PPTX/TXT/MD, with an incremental NumPy index;
  - cited `/ask` answers;
  - map-reduce digest with an XLSX matrix;
  - harvested and curated content blocks; storyline outline; per-slide deck writer with review
    guards;
  - deterministic PPTX renderer with a QA report;
  - offline research with a call cap;
  - sandboxed agents (OpenCode, Claude Code via Ollama).
- **Router:**
  - commands and aliases, rules → classifier, and confirmation for actions that write files;
  - commands pasted in code fences are recognised;
  - "files + question" ingests first, then answers;
  - working modes, plus `/chat` with conversation history;
  - the model and effort can be chosen per message.
- **App** (`src/studio/ui/`):
  - **Server:** Python's built-in HTTP server on 127.0.0.1, with SSE streaming.
  - **Security:** a per-launch token (HttpOnly, SameSite=Strict cookie, and a header required for
    writes), Host/Origin checks, and agent settings can't be changed from chat.
  - **Projects:** each project lives in a folder you trust. Folders are always shown with
    **Open folder**. A project can be removed from the list or deleted with its folder.
  - **Front end:** a modular UI with a warm paper + ink look and dark mode; a sidebar that
    collapses to icons; a resizable side panel.
  - **Pages:** home, projects grid, project page, chat, Settings, with in-app dialogs.
  - **Composer:** a Finder-style folder picker, search, pinned and temporary chats, and mode and
    model chips.
  - **Document viewer:** PDF pages with a selectable text layer, a reading view for Office files,
    find and zoom, and highlights for citations.
- **Docs:** README, `docs/` (install, commands, config, templates, agents, troubleshooting,
  privacy), and an offline `tutorial.html`.

## Problems that real runs caught (all fixed)

- **qwen3:8b:**
  - It mis-copied citation labels; it now cites by number, and Python adds the labels.
  - It stamped one example id on every requirement; ids are now checked against the RFP.
  - It imported a past client's claims into the deck; the guards now flag them.
- **Harvest:** client names leaked into review notes; the notes are now anonymised.
- **Open WebUI era:** a FAISS/torch OpenMP crash led to NumPy search, and the confirmation dialog
  could auto-approve. Both were fixed before Open WebUI was removed.
- **App:**
  - folder chooser bugs;
  - dialogs that stayed open across pages;
  - a stray "null" chip;
  - a CSS clash in the search dialog;
  - over-wide grid columns next to the panel;
  - citations from tables that can't be matched word for word (the section heading is now
    highlighted instead).

## Still open

- **Next phases:** 16 shared drives, 17 notebook, 18 Outputs/Templates/Customize, 19 research +
  opt-in web, 20 model-router suggestions.
- **Not yet run for real:**
  - the Windows scripts on a Windows 11 laptop;
  - the 16 GB Intel CPU-only target;
  - a visual check of a rendered deck in PowerPoint;
  - Linux (the last CI run failed on Ubuntu, cause unknown).
- **Quality limits with qwen3:8b:**
  - agents rarely use their file tools;
  - the research synthesis isn't cited;
  - deck quality depends on curated blocks.
- **Release:** v0.1.0 was never shipped. `/ship` now builds the files locally, and you publish
  the GitHub Release by hand.
- **Before publishing:** confirm your employment terms and your firm's tool policy allow it.

---

# Phase log

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
