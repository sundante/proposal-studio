# Performance

Budget (spec §15): rules routing < 1 s, classifier < 15 s, `/ask` first token < 60 s, one slide
< 2 min, full deck 10–20 min, `/render` < 10 s, Open WebUI + studio idle RAM < 2 GB (excluding
the loaded model).

Measure your own machine with `studio bench` (add `--cpu` to force CPU-only inference). It runs a
synthetic RFP in a throwaway folder and prints this table.

## Measured (2026-11-04, qwen3:8b worker, qwen3:4b router, nomic-embed-text)

Apple-silicon Mac, Ollama 0.40, Open WebUI 0.13.0:

| Step | Default (GPU) | CPU only (`--cpu`) | Budget |
|---|---:|---:|---|
| Rules routing | 0.0 s | 0.0 s | < 1 s ✅ |
| Classifier routing | 4.4 s | 11.7 s | < 15 s ✅ |
| `/ask` first token | 5.7 s | 17.8 s | < 60 s ✅ |
| `/digest` (synthetic 3-page RFP) | 51.5 s | 99.4 s | — |
| `/deck` one slide | 6.0 s | 21.3 s | < 2 min ✅ |
| `/render` | 0.1 s | 0.1 s | < 10 s ✅ |
| Open WebUI + studio idle RSS | 736 MB | — | < 2 GB ✅ |

**Full deck:** the benchmark folder has no block library, so most slides come out as
skeletons and its "full deck" time (10–18 s) understates the real cost. With a curated library,
expect about the one-slide time × ~10 slides: **~3.5 min CPU-only on this Mac**.

**On the 16 GB Intel CPU-only target**, expect CPU-only figures 2–4× slower than the column
above. That still fits the budget for routing, `/ask` and single slides, and gives ~10–15 min
for a full deck. Reports from real target machines are welcome.

## Tuning already applied

- **`think: false`** (qwen3 thinking off) everywhere by default.
- **Worker `num_ctx` 8192**: the largest prompt (`/ask` with 6 × 800-token excerpts) fits, and
  the KV cache uses half the memory of 16k. The router uses 4096.
- **One model at a time**: `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, and a
  single-flight lock inside studio. `studio doctor` warns if several models are loaded.
- **Background work stays off**: Open WebUI's title, tag and follow-up generation is disabled,
  so it doesn't compete with your requests.
- **No LLM where Python will do**: rules routing, rendering, de-duplication, citation mapping,
  and the title slide.
- **No LLM for current digests**: an auto-routed `/digest` shows the saved digest when it's
  current.

## If it's too slow

- Use the smaller worker: `/config set worker.model qwen3:4b`. It's faster but a little weaker
  at extraction.
- Lower `rag.top_k` (default 6) for shorter `/ask` prompts.
- Ingest only the RFP documents that matter: annexes and boilerplate make `/digest` longer.
- Regenerate single slides (`/deck <slide_id>`) rather than the whole deck.
