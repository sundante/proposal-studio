# Troubleshooting

Start with `studio doctor`. It checks Python, the config, whether the workspace is writable,
whether Ollama is reachable (and its version), and whether each configured model is pulled.

| Symptom | Fix |
|---|---|
| "Ollama isn't running at http://localhost:11434" | Start it: `ollama serve`, or run `scripts/start.*`, which starts it. |
| "Model qwen3:8b isn't pulled" | `ollama pull qwen3:8b` (while online). |
| The Proposal Studio model doesn't appear in Open WebUI | Admin Panel → Functions: is it enabled? Re-run `studio owui install --token …`. |
| "can't find its project folder" in chat | Set the `STUDIO_HOME` valve (Admin → Functions → Proposal Studio → Valves), or start Open WebUI with `scripts/start.*`. |
| `ModuleNotFoundError: studio` in Open WebUI | `studio` isn't installed in Open WebUI's venv. Run `scripts/setup.*`, or `pip install -e .` inside that venv. |
| Open WebUI answers from its own RAG instead of `/ask`, or `/commands` aren't recognised after attaching files | Workspace → Models → Proposal Studio → Capabilities → untick **File Context**, and start with `scripts/start.*` (it sets `RAG_SYSTEM_CONTEXT=True`). |
| Ollama loads several models / RAM fills up | Quit the Ollama tray app and let `start.*` launch Ollama, so `OLLAMA_MAX_LOADED_MODELS=1` applies. |
| `OMP: Error #15 … libomp already initialized` | This came from FAISS, which Proposal Studio no longer uses. Remove `faiss-cpu` from the venv (`pip uninstall faiss-cpu`) if an old install left it there. |
| "Possible PHI found" on ingest | RFPs shouldn't contain PHI. Check the listed file/page; re-run with `/approve` (or `--yes`) only if it's a false positive. |
| `/render` QA errors about layouts | The mapping in `config/layout_map.yaml` doesn't match the template. See [templates.md](templates.md) (`studio template inspect`). |
| Slides say "Add content — no vetted blocks" | Harvest and curate blocks first: `/harvest`, then review `library/blocks/*.yaml`. |
| Answers repeat the same excerpt twice | You ingested the same RFP as both PDF and DOCX. Keep one format per document: remove one from `workspace/<opp>/input/` and send `/ingest`. |
| Everything is slow | Expected on CPU-only laptops. See [performance.md](performance.md). Use `qwen3:4b` for the worker (`/config set worker.model qwen3:4b`), and keep RFP files focused. |
| An agent "isn't installed" | Install its CLI (see [agents.md](agents.md)) and make sure it's on PATH. |
| Windows: "running scripts is disabled" | Run with `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`. No admin is needed. |

Logs:
- Open WebUI: its console window.
- Agents: `workspace/<opp>/agent/logs/`.
- Ollama: `.owui-data/ollama.log` when it was started by `start.sh`.
