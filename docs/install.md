# Install Proposal Studio

> Prefer a guided walk-through? See the [tutorial](../vibes/tutorial.html) (one offline HTML file).

Proposal Studio runs entirely on your machine:
- the **Proposal Studio app** (`studio ui`) is the chat window in your browser;
- [Ollama](https://ollama.com) runs the models;
- the `studio` Python package does the work.

Internet is needed **only during setup**, to download Python packages and models.

## 1. Prerequisites (no admin rights needed)

- **Python 3.11 or newer**, installed for your user (python.org installer → "Install for me only").
- **Ollama**, installed for your user from https://ollama.com.
- About 9 GB of disk (models ≈ 8 GB) and 16 GB RAM.

## 2. Set up (online, once)

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

macOS / Linux:

```bash
scripts/setup.sh
```

The script:
- is safe to re-run;
- creates `.venv` and installs `studio` into it;
- pulls the models named in `config/models.yaml`: `qwen3:8b`, `qwen3:4b` and `nomic-embed-text`;
- prints anything it couldn't do.

## 3. Start (offline from here on)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1     # Windows
```

```bash
scripts/start.sh                                              # macOS / Linux
```

`start` does three things:
1. Applies `scripts/offline.env`: one model loaded at a time, Ollama cloud features off, and no
   library telemetry.
2. Makes sure Ollama is running.
3. Runs `studio ui`, which opens **http://127.0.0.1:8765/?t=…** in your browser.

The app listens on 127.0.0.1 only. The `?t=…` link unlocks it for this session, so keep it
private. If you close the tab, open the link from the terminal again.

> On Windows, if the Ollama tray app is already running, the `OLLAMA_*` settings in
> `offline.env` don't reach it. Quit the tray app before `start.ps1` so it starts Ollama itself.

## 4. Choose a workspace folder

The first thing the app asks for is a **workspace folder** it may read and write, for example
`Documents\Bids\Acme 2026`, and you confirm that you **trust** it. Nothing outside it is
touched. Inside it:

| Folder | Holds |
|---|---|
| `projects/` | one folder per bid: uploaded files, chats, the index, the digest, deck.json, outputs |
| `library/` | your past proposals, reference documents and curated content blocks |
| `.studio/` | the workspace marker, caches and logs |

The list of trusted folders is kept for your user account, outside every workspace:
- Windows: `%APPDATA%\ProposalStudio\trusted.json`
- macOS/Linux: `~/.proposal-studio/trusted.json`

Switch workspaces from the folder name at the top of the sidebar. To skip the question at
launch, tick **Open this workspace automatically next time**.

## 5. Use it

1. Drop the RFP (PDF, Word, Excel, PowerPoint or text) onto the page. A project is created and
   the files are read, PHI-checked and indexed.
2. Ask questions in plain language. Answers cite `[section, p.N]`.
3. Click **Analyse RFP** for the summary (requirements, criteria, compliance, risks). It appears
   in the side panel.
4. Click **Build slides** to write the deck and render it on your template, then
   **Download PPTX**.

Layout:
- **Ctrl/⌘+B** collapses the sidebar.
- **Ctrl/⌘+J** shows or hides the side panel.
- Drag the panel's edge to widen it; double-click the edge to toggle between wide and normal.
- Click the model status at the bottom of the sidebar to see installed models and choose which
  one does what.

Slash commands still work for power users. See [commands.md](commands.md).

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

This runs `studio doctor`, then pushes a synthetic RFP through ingest → ask → digest → outline →
deck → render on the real models, in a throwaway folder. Expect a few minutes on a CPU-only
laptop.

## Upgrading

Download the new release (or `git pull`) and re-run `setup`. These are kept:
- your workspace folders;
- `templates/` (your own templates);
- `config/overrides.yaml`.

Upgrading from the Open WebUI version (0.1.x development builds):
- The Open WebUI setup was removed. It is archived on the `archive/open-webui` branch.
- To keep old projects, move the folders from `workspace/` into a trusted workspace's
  `projects/` folder, and `library/` into its `library/`.
