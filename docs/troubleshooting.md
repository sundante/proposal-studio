# Troubleshooting

Start with `studio doctor`. It checks Python, the config, whether the workspace is writable,
whether Ollama is reachable (and its version), and whether each configured model is pulled.

| Symptom | Fix |
|---|---|
| "Ollama isn't running at http://localhost:11434" | Start it: `ollama serve`, or run `scripts/start.*`, which starts it. |
| "Model qwen3:8b isn't pulled" | `ollama pull qwen3:8b` (while online). |
| The page says "Open Proposal Studio from its link" | The page only works from the `http://127.0.0.1:8765/?t=…` link that `studio ui` prints (a new one each launch). Open it again from the terminal. |
| "No config/ folder" when starting | Run `studio ui` from the project folder, or set `STUDIO_HOME`; `scripts/start.*` does this for you. |
| "… is a system folder" / "too broad" when choosing a project folder | Pick or create a folder for the bid, e.g. `Documents\Bids\Acme`; whole drives, your home folder itself and system folders can't be used. |
| A project shows "Folder missing" | Its folder was moved or deleted outside the app. Click it → **Remove from Proposal Studio**, then add the moved folder back with **New project → Choose another folder…**. |
| "Where are my files?" | The sidebar shows each project's path; the **Files** tab shows it in full, with **Open folder**. **Settings** shows the Proposal Studio folder and library. |
| Port 8765 is in use | `studio ui --port 8766` (or pass the same option to `scripts/start.*`). |
| Ollama loads several models / RAM fills up | Quit the Ollama tray app and let `start.*` launch Ollama, so `OLLAMA_MAX_LOADED_MODELS=1` applies. |
| `OMP: Error #15 … libomp already initialized` | This came from FAISS, which Proposal Studio no longer uses. Remove `faiss-cpu` from the venv (`pip uninstall faiss-cpu`) if an old install left it there. |
| "Possible PHI found" on ingest | RFPs shouldn't contain PHI. Check the listed file/page; re-run with `/approve` (or `--yes`) only if it's a false positive. |
| `/render` QA errors about layouts | The mapping in `config/layout_map.yaml` doesn't match the template. See [templates.md](templates.md) (`studio template inspect`). |
| Slides say "Add content — no vetted blocks" | Harvest and curate blocks first: `/harvest`, then review `library/blocks/*.yaml`. |
| Answers repeat the same excerpt twice | You ingested the same RFP as both PDF and DOCX. Keep one format per document: remove one in the **Files** tab (or from the project's `input/` folder). |
| Everything is slow | Expected on CPU-only laptops. See [performance.md](performance.md). Use `qwen3:4b` for the worker (`/config set worker.model qwen3:4b`), and keep RFP files focused. |
| An agent "isn't installed" | Install its CLI (see [agents.md](agents.md)) and make sure it's on PATH. |
| Windows: "running scripts is disabled" | Run with `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`. No admin is needed. |

Logs:
- The app: its terminal window.
- Agents: `agent/logs/` inside the project folder.
- Ollama: `$TMPDIR/proposal-studio-ollama.log` when it was started by `start.sh`.
