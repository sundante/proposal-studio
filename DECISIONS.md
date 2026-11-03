# Decisions log

Append-only. One entry per decision or deviation from `PROJECT_SPEC.md`.

Format:
```
## YYYY-MM-DD — <short title>  (Phase N)
- Context:
- Decision:
- Why:
- Spec impact: (section + what changed, or "none")
```

## 2026-11-03 — Foundational decisions  (pre-build)
- Context: Planning session.
- Decision: Fully local + offline runtime; Open WebUI as UI; deterministic Python router with
  slash commands + auto-routing; agent CLIs (Claude Code, OpenCode, Hermes Agent) called headlessly
  in a sandbox with two-phase approval; offline research over a local library; decks built from
  harvested, anonymised blocks on a fixed storyline; renderer uses the user's own template and no
  LLM; open-source on GitHub under Apache-2.0, installed from Releases.
- Why: 16 GB CPU-only target, no admin/Docker, US-healthcare data constraints, reproducible
  formatting, public distribution.
- Spec impact: none (this is the baseline).

## 2026-11-03 — Pre-build ambiguity resolutions  (kickoff)
- Context: Kickoff review of PROJECT_SPEC.md before Phase 0.
- Decision:
  1. Dev Python: uv-managed 3.11 venv (`uv venv --python 3.11 .venv`). CI covers 3.11 + 3.12.
     3.11 is preferred at runtime because Open WebUI shares the venv.
  2. Token counts for chunking (~800 tokens / 100 overlap) are approximated as `len(text) / 4`.
     No tokenizer dependency.
  3. LLM access goes through an `LLMClient` Protocol in `studio/llm.py`. Modules receive the client
     as a parameter; `OllamaClient` is the real implementation, `tests/fakes.py::FakeLLM` the fake.
  4. Shared `Cite {section, page}` and similar cross-module models live in `studio/models.py`.
  5. `/config set` takes dotted paths into the config model; `<role>.<field>` is shorthand for
     `roles.<role>.<field>`. Overrides are deep-merged from `config/overrides.yaml`, validated with
     `extra="forbid"`.
  6. Project root discovery: env var `STUDIO_HOME`, else the current working directory. `config/`,
     `workspace/`, `library/`, `templates/` resolve against it.
  7. Structured output relies on Ollama's JSON-schema `format` (Ollama >= 0.5); `studio doctor`
     reports the Ollama version from `/api/version`.
  8. Single-flight generation lock is a process-wide `threading.Lock` with an `on_wait` status
     callback, usable from the sync CLI and from the async pipe (via a worker thread).
- Why: Removes guesswork that would otherwise change the shape of Phases 0–3.
- Spec impact: §3 adds `src/studio/models.py`; §6 notes the `LLMClient` Protocol.

## 2026-11-03 — Known environment risks  (kickoff)
- Context: Target is Windows 11, 16 GB, CPU-only, no admin.
- Decision: Track, don't block:
  - `pip install open-webui` pulls torch + sentence-transformers (multi-GB); the <2 GB idle RAM
    budget (§15) is at risk. Revisit in Phase 9 (e.g., embeddings via Ollama, lazy imports).
  - Hermes Agent may lack a native Windows/headless mode; expect "unsupported headless" in Phase 8.
- Why: Visibility for later phases.
- Spec impact: none.

## 2026-11-03 — Ingest + RAG implementation choices  (Phase 1)
- Context: Building §7 (ingest, FAISS RAG, `/ask`).
- Decision:
  1. New `config/rag.yaml` (`chunk_tokens`, `chunk_overlap`, `top_k`, `min_score`) validated as
     `RagConfig`; `/config set top_k 8` works via the `rag.` shorthand.
  2. PDF headings: a line is a heading if its font is >= 1.15x the body median, or it matches
     numbered-heading text (`3.2 Scope`) and is bold/larger. Level = numbering depth, else font
     size rank. PDF table cells are read with `page.get_textbox(cell)` because
     `Table.extract()` dropped spaces on generated PDFs. DOCX `Title` is treated as level 1 so it
     doesn't prefix every citation.
  3. FAISS: `IndexIDMap2(IndexFlatIP)` over L2-normalised vectors (cosine). Serialised with
     `faiss.serialize_index` + Python file I/O (atomic replace), avoiding faiss's C `fopen` on
     non-ASCII Windows paths. Changing the embedding model clears and rebuilds the index.
  4. `/ask` citations: the model cites excerpt numbers (`[2]`), and Python rewrites them into
     the exact `[section, p.N]` labels while streaming. A real qwen3:8b run showed the model
     mis-copying long labels; numbers are reliable and keep formatting out of the LLM. Answers
     without a valid cite get a "Sources" footer; unknown cites are flagged.
  5. "Not found in the RFP." is returned with no LLM call when the best retrieval score is below
     `min_score`, and also when the model replies `NOT_FOUND`.
  6. PHI on ingest: nothing is copied or indexed until confirmed; the CLI exits with code 2 and
     asks for `--yes`.
- Why: Deterministic, testable behaviour on small local models.
- Spec impact: §3 adds `config/rag.yaml`.

## 2026-11-03 — Git workflow: dev + main only  (process)
- Context: Maintainer prefers to promote releases manually.
- Decision: Only `dev` and `main` exist. All work is committed and pushed to `dev`; the maintainer
  promotes `dev` → `main`. No phase branches or PRs. CI runs on pushes to both; Dependabot
  targets `dev`. `/ship` commits the release bump on `main` after promotion.
- Why: Simpler flow for a single maintainer.
- Spec impact: §16.1 ("work happens on `phase/<n>-<slug>` branches merged by PR") superseded.
