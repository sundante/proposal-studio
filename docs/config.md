# Configuration

All settings live in `config/*.yaml` and are validated on load: unknown keys and cloud models are
rejected. **Don't edit the base files for personal changes.** Use `/config set` (or
`studio config set`), which writes `config/overrides.yaml`. That file is gitignored and survives
upgrades. `/config reset` removes it.

```
/config                                  # effective settings
/config set worker.model qwen3:4b        # shorthand for models.roles.worker.model
/config set auto_threshold 0.8           # shorthand for routes.auto_threshold
/config set top_k 8                      # shorthand for rag.top_k
/config reset
```

| File | What it controls |
|---|---|
| `models.yaml` | Ollama URL; one model per role (`router`, `worker`, `embed`) with `num_ctx`, `temperature`, optional `num_gpu` (0 = CPU only); `keep_alive`; `think` (off by default for speed); `block_cloud_models` (always on in practice) |
| `routes.yaml` | Commands and help, aliases, auto-route keywords, classifier examples, `auto_threshold`, `confirm_routes` |
| `rag.yaml` | Chunk size/overlap, `top_k`, `min_score` (below → "Not found in the RFP."), digest group size, de-duplication similarity |
| `deck.yaml` | Blocks per slide, minimum block score, minimum harvest unit size, whether to use blocks still marked `needs_review` |
| `storyline.yaml` | The fixed deck spine: slide ids, types, `required`, `include_if` rules, `max_items` |
| `layout_map.yaml` | Your template path, text limits, slide type → layout + placeholder mapping (see [templates.md](templates.md)) |
| `research.yaml` | `/research` LLM-call cap, sub-question count, retrieval sizes, sources |
| `agents.yaml` | Agent CLI command templates, env, sandbox copy-in list, timeout (see [agents.md](agents.md)) |

`STUDIO_HOME` sets the app folder (where `config/` and `templates/` live); without it, the current
folder is used, and the start scripts set it for you. In the app, projects and the library live
in the **workspace folder** you trust (`projects/`, `library/`); the CLI keeps using
`workspace/` and `library/` under `STUDIO_HOME`. The list of trusted folders is per user
(`$STUDIO_USER_DIR` overrides where it's kept). `/config set agents.…` is refused in the app.

## `include_if` rules (storyline.yaml)

Optional slides are included when **any** rule matches the digest:

```yaml
include_if: ["compliance contains HITRUST", "risks_and_red_flags not empty", "requirements count >= 10"]
```

The `/outline` reply says which rule matched, and cites the RFP.

## Choosing models

The defaults suit a 16 GB laptop. `qwen3:4b` is faster but weaker at extraction. Larger models
need more RAM, and only one model is loaded at a time (`OLLAMA_MAX_LOADED_MODELS=1`). Cloud models
(`…:cloud`, `…-cloud`) are always refused.
