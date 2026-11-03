# Install Proposal Studio

> Prefer a guided walk-through? See the [tutorial](../tutorial.html) (one offline HTML file).

Proposal Studio runs entirely on your machine: [Open WebUI](https://github.com/open-webui/open-webui)
is the chat UI, [Ollama](https://ollama.com) runs the models, and the `studio` Python package does
the work. Internet is needed **only during setup** (Python packages and model downloads).

Tested with Open WebUI **0.13.0** and Python **3.11** (Open WebUI supports 3.11–3.12).

## 1. Prerequisites (no admin rights needed)

- **Python 3.11 or 3.12**, installed for your user (python.org installer → "Install for me only").
- **Ollama**, installed for your user from https://ollama.com.
- About 12 GB of disk (Open WebUI ≈ 3 GB, models ≈ 8 GB) and 16 GB RAM.

## 2. Set up (online, once)

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

macOS / Linux:

```bash
scripts/setup.sh
```

The script is safe to re-run. It creates `.venv`, installs `open-webui` and `studio` into it, and
pulls the models named in `config/models.yaml` (`qwen3:8b`, `qwen3:4b`, `nomic-embed-text`). It
prints anything it couldn't do.

## 3. Start (offline from here on)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1     # Windows
```

```bash
scripts/start.sh                                              # macOS / Linux
```

`start` applies `scripts/offline.env`: offline mode, no web search, no image generation, no
community sharing, no telemetry, no update checks, Ollama as the only model backend (cloud
features off, one model loaded at a time), and Open WebUI's background title/tag generation
turned off. Open WebUI listens on **127.0.0.1:8080** only and keeps its data in `.owui-data/`
(never commit it).

> On Windows, if the Ollama tray app is already running, the `OLLAMA_*` settings in
> `offline.env` don't reach it. Quit the tray app before `start.ps1` so it starts Ollama itself.

Open http://localhost:8080 and create the first account. It becomes the admin and stays local.

## 4. Add Proposal Studio to Open WebUI

### Option A — automated

1. In Open WebUI: **Settings → Account → API keys → Create new secret key** (copy the `sk-…`).
2. In a terminal in the project folder:

   ```bash
   .venv/bin/studio owui install --token sk-...            # Windows: .venv\Scripts\studio.exe
   ```

   This creates or updates the **Proposal Studio** pipe and the **PHI warning** filter, enables
   them, and adds one Prompt per command, so typing `/` lists them. It only talks to `localhost`.

### Option B — by hand

1. **Admin Panel → Functions → +** (New Function): paste `owui/router_pipe.py`, save, and enable.
2. Same again for `owui/phi_filter.py`. Then enable the filter for the Proposal Studio model
   (Workspace → Models → Proposal Studio → Filters), or globally.
3. **Workspace → Prompts → Import**: choose `owui/prompts/all.json`.

### Then, once

- **Valves** (Admin Panel → Functions → Proposal Studio → ⚙):
  - `STUDIO_HOME`: the project folder. `start` already sets this as an environment variable, so
    you can leave it empty.
  - `AUTO_ROUTE` / `AUTO_THRESHOLD`: plain-text routing.
- **User Valves** (chat → Controls): `DEFAULT_OPPORTUNITY` for new chats.
- **File Context off**: Workspace → Models → Proposal Studio → Capabilities → untick
  *File Context*. Proposal Studio reads attachments itself, and this stops Open WebUI from also
  running its own RAG over them.
- **Light theme**: Settings → General → Theme → Light. There's no server-wide default.

## 5. Use it

Pick the **Proposal Studio** model and type `/help`. A typical flow:

```
/new acme-2026 Acme Health Plan AI platform
(attach the RFP files and send)        → routed to /ingest
When are proposals due?                → routed to /ask, with [section, p.N] citations
/digest xlsx                           → digest + requirements matrix (download link)
/outline   →   /deck   →   /render     → PPTX download link + QA report
```

Commands that write files (`/render`, `/harvest`, `/agent`) never run from plain text without
confirmation. You'll get a confirmation dialog, or you can type `/approve`.

## Optional: agent CLIs

`/agent` can hand file tasks to local agent CLIs (see [agents.md](agents.md)). Install them
while online, at user level:

```bash
npm install -g opencode-ai @anthropic-ai/claude-code   # or into a user npm prefix
```

## 6. Check the install

```bash
scripts/smoke_test.sh            # Windows: scripts\smoke_test.ps1
```

This runs `studio doctor`, then a synthetic RFP through ingest → ask → digest → outline → deck →
render on the real models, in a throwaway folder. Expect a few minutes on a CPU-only laptop.

## Upgrading

Download the new release (or `git pull`) and re-run `setup`. `library/`, `workspace/`,
`templates/` (your own templates), `config/overrides.yaml` and `.owui-data/` are kept. Re-run
`studio owui install` to update the functions.
