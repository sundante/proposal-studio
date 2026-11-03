# Decisions log

Append-only. One entry per decision or deviation from `vibes/PROJECT_SPEC.md`.

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
- Context: Kickoff review of vibes/PROJECT_SPEC.md before Phase 0.
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

## 2026-11-03 — RFP digest implementation choices  (Phase 2)
- Context: Building §8 (map-reduce digest) and testing on qwen3:8b with the synthetic Acme RFP.
- Decision:
  1. All citation fields are lists (`evidence: list[Cite]`, `cite: list[Cite]`), so merged
     duplicates keep every citation ("keep all citations" in BUILD_PLAN Phase 2).
  2. Map step: the model cites excerpt numbers (`excerpts: [2]`); Python maps them to `Cite`,
     ignores invalid numbers and drops items left uncited (counted in the run's warnings).
  3. Requirement ids are checked in Python: the model's `rfp_id` is kept only if a cited line
     prints it and is about that requirement; otherwise the id is read from the cited line
     (`ID: R-01` field or a leading `R-01`/`3.2.1`), else `REQ-NNN` is assigned. Requirements
     sharing an id merge only if their wording overlaps. A real run showed qwen3:8b copying the
     prompt's example id onto every requirement.
  4. De-duplication: normalised text first, then embedding cosine >= `rag.dedupe_similarity`
     (0.9). Citations of one section with and without a page (same RFP as PDF + DOCX) collapse
     to the paged one.
  5. Conflicting opportunity facts (e.g. two due dates) keep the first value and add a
     "Conflicting …" entry to `risks_and_red_flags`.
  6. New `rag.yaml` keys: `digest_group_tokens` (2000) and `dedupe_similarity` (0.9).
     `digest.meta.json` stores source hashes so `status` can report a stale digest.
- Why: Small local models are unreliable at ids and labels; Python checks keep the digest
  trustworthy.
- Spec impact: §8 `evidence`/`cite` fields become lists.

## 2026-11-03 — Non-functional docs move to `vibes/`  (process)
- Context: Maintainer wants planning/tracking docs out of the repo root.
- Decision: `PROJECT_SPEC.md`, `BUILD_PLAN.md`, `PROGRESS.md`, `DECISIONS.md`, `START_HERE.md`
  live in `vibes/`, plus a new narrative `vibes/status.md` refreshed each phase. Files tools or
  GitHub expect at the root stay there (README, LICENSE, CHANGELOG, CONTRIBUTING,
  CODE_OF_CONDUCT, SECURITY, CLAUDE.md, AGENTS.md, `.claude/`, `.github/`). All references
  updated to `vibes/...`.
- Why: Cleaner root for an open-source repo.
- Spec impact: §3 layout updated.

## 2026-11-03 — Template + renderer choices  (Phase 3)
- Context: Building §9.3/§9.5 (slide schemas, inspector, `.potx`, renderer, QA).
- Decision:
  1. VERIFY `.potx`: python-pptx 1.0.2 rejects a `.potx` (ValueError on the template content
     type). `open_template` loads an in-memory copy with `[Content_Types].xml` patched from
     `…presentationml.template.main+xml` to `…presentation.main+xml`; the file on disk is never
     touched. Works; no "Save As .pptx" step needed.
  2. VERIFY slide removal: dropping each `sldId` and its relationship removes the template's
     sample slides and their parts cleanly; output reopens fine.
  3. `layout_map.yaml` is typed: `limits` (global) + per-`slide_type` `LayoutSpec{layout,
     placeholders: field → idx|name, limits overrides, diagram_area}`.
  4. Schemas are lenient for loading `deck.json`; limits are checked and enforced at render time
     (word-boundary truncation with "…", item trimming, all reported in QA). `slide_model()`
     builds strict per-type models with `maxLength`/`maxItems` for the Phase 4 writer's schema.
  5. Unfilled placeholders are deleted from rendered slides, so no "Click to add text" prompts
     remain; a mapped-but-empty field is reported as an empty placeholder.
  6. Sample template: generated in code from python-pptx's bundled generic default (no brand
     assets), widened to 16:9 (only shapes with their own position are rescaled; inherited
     placeholders follow the master), light palette, one accent bar, neutral footer, two
     throwaway slides. Committed at `templates/sample/proposal-sample.pptx`; a test checks it
     matches a fresh build.
  7. Mapping errors (unknown slide type, layout or placeholder) skip that slide and are QA
     errors; `studio render` exits 1 when QA has errors.
  8. Ruff: `typer.Option`/`typer.Argument` marked immutable for B008 (typer's documented style).
- Why: Deterministic, testable rendering on any user template.
- Spec impact: none beyond the above clarifications.

## 2026-11-03 — Blocks, storyline and deck writer choices  (Phase 4)
- Context: Building §9.1/§9.2/§9.4 and running it on qwen3:8b with a synthetic "Example
  Hospital" library and the Acme RFP digest.
- Decision:
  1. New `config/deck.yaml` (`DeckConfig`): `blocks_per_slide` (3), `min_block_score` (0.2),
     `harvest_min_chars` (80), `include_flagged_blocks` (false).
  2. Harvest units = one PPTX slide or one DOCX/PDF section. After the model, Python anonymises
     again: client names (model-reported + `--client`) → `{{client}}`, dates (incl. "March 3")
     → `{{date}}`, amounts → `{{amount}}`, emails/phones dropped. The model's `uncertain` notes
     are anonymised too and restatements are dropped (a real run leaked the client name into
     review notes and flagged every block). Remaining percentages/multipliers set
     `needs_review`. `HarvestResult` fields are all required so the model fills tags/capability.
  3. Blocks are protected from re-harvest if `edited: true` **or** their content hash no longer
     matches (hand edits are detected without the flag). Ids are stable per source unit; an
     unchanged source makes no LLM call (`library/.index/harvest.json`).
  4. `include_if` grammar: `<field> contains <text>`, `<field> not empty`,
     `<field> count >= N`; several rules are OR'd. Optional slides without rules are included by
     default. `/toggle` choices persist across `/outline` rebuilds.
  5. Writer LLM schema = `slide_model(enforce=False)` + `used_blocks`/`used_facts` numbers;
     limits are stated in the prompt and enforced in Python (one shorten retry, then truncate +
     flag). Grammar-enforced `maxLength` would cut words mid-way.
  6. Guards that flag (never silently remove), stored in each slide's `review` and surfaced as
     render QA warnings: figures/certifications absent from blocks and RFP facts; on
     client-facing slides (understanding, before_after) statements sharing almost no words with
     any RFP fact; block `{{date}}`/`{{amount}}` slots filled with concrete values. The prompt
     rules alone did not stop qwen3:8b from importing a past client's claim or filling a
     placeholder with the proposal due date — the Python guards catch both.
  7. Vendor slides with no vetted blocks become visible skeletons ("Add content — run
     /harvest"); client-facing slides may be written from RFP facts alone (flagged). The title
     slide is deterministic from the digest.
  8. Every deck write copies the previous `deck.json` to `history/deck-<ts>.json`.
- Why: Small local models drift; provenance and Python checks keep the deck honest.
- Spec impact: §9.3 slides gain `review: list[str]`; §3 adds `config/deck.yaml`.

## 2026-11-03 — Offline research choices  (Phase 5)
- Context: Building §11 (`/research`) and running it on qwen3:8b over a synthetic library.
- Decision:
  1. No LangGraph: `research.py` is a small explicit loop (plan → multi-query retrieval →
     per-sub-question findings → one gap round → synthesis). Easier to test and to cap.
  2. Library indexing: `ingest.index_files()` is the shared core (hash, extract, PHI scan,
     chunk, embed). `/ingest` copies RFP files into the opportunity; `studio library index`
     indexes `library/{proposals,reference}` in place, subfolders included, named by relative
     path; deleted files are removed. PHI hits block indexing until `--yes`.
  3. New `config/research.yaml` (`ResearchConfig`): `max_llm_calls` 12, `max_sub_questions` 5,
     `top_k_per_query` 4, `excerpts_per_question` 6, `weak_score` 0.35, `sources`.
  4. The call cap counts logical model requests (each may include `generate_structured`'s own
     validation retries). One call is always reserved for synthesis; the plan is sized to the
     budget, and the gap round is skipped (with a note) when it can't fit.
  5. Rephrasings come from the planning call (not one call per sub-question) to save budget.
  6. Findings cite excerpt numbers; Python maps them to `[file, p.N]` / `[file, slide N]` and
     drops uncited points. A sub-question is weak if it has no points, evidence isn't
     "strong", or its best retrieval score is below `weak_score`.
  7. With no active opportunity, research runs on the library alone and saves to
     `workspace/research/`; otherwise it includes the RFP and saves to
     `workspace/<opp>/research/`. Reports never overwrite (`-2`, `-3`…).
- Why: Bounded, testable research on a 16 GB CPU-only machine.
- Spec impact: §3 adds `config/research.yaml`.
