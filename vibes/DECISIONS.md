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

## 2026-11-03 — Router choices  (Phase 6)
- Context: Building §5 (commands, auto-routing, sessions) and a `studio chat` REPL; tested on
  qwen3:4b (router) / qwen3:8b (worker).
- Decision:
  1. `studio/views.py` holds the text formatting shared by the CLI and the router, so
     `studio <cmd>` and `/<cmd>` say the same thing.
  2. Extra commands beyond §5.1: `/approve` (`/yes`) and `/reject` (`/no`) — the confirmation
     fallback for routes in `confirm_routes` and for PHI warnings — and `/library index|status`
     (needed by `/research`). `/agent` is a placeholder until Phase 8.
  3. `Router.handle()` runs routing + the handler in a worker thread and bridges chunks and
     status callbacks through an asyncio queue, so sync httpx/LLM work never blocks the event
     loop. Status events use the Open WebUI shape
     `{"type": "status", "data": {"description", "done"}}` (verify in Phase 7).
  4. Rules before the classifier: attachments-only → `/ingest`; `routes.keywords` → route;
     "?" with an indexed active RFP → `/ask`. The classifier (`router` role,
     `RouteDecision{route, alternative, confidence, args}`) excludes session/meta commands.
     Below `auto_threshold` → "Did you mean `/x` or `/y`?". Classifier failure → clarification.
  5. Pending confirmations live in `session.last_outputs["pending"]` (command, args,
     attachments) and survive restarts with the session.
  6. Path policy: typed paths in `/ingest` work only when `allow_local_paths` (the REPL);
     the chat UI must use attachments.
  7. `deck` keywords narrowed (a bare "slide " would send "which slide covers X?" into a
     multi-minute deck rewrite).
  8. Auto-routed `/digest` shows the saved digest when it is current; only an explicit
     `/digest` rebuilds (a real run rebuilt it for "summarise the requirements": 116 s).
- Why: Deterministic, transparent routing that never surprises the user with slow or
  file-writing work.
- Spec impact: §5.1 gains `/approve`, `/reject`, `/library`.

## 2026-11-03 — VERIFY: Open WebUI 0.13.0 integration facts  (Phase 7)
- Context: Verified against the `open-webui==0.13.0` wheel source (requires Python >=3.11,<3.13)
  before writing `owui/`. Ollama env vars checked with `ollama serve --help`.
- Findings:
  1. Functions are Python files `exec`'d by Open WebUI; the module must define `Pipe` (or
     `Filter`). A docstring frontmatter `requirements:` line is pip-installed on load, so our
     functions declare none (the `studio` package is installed in the same venv instead).
  2. `pipe(body, …)` receives only the extras it declares: `__user__` (dict; `valves` =
     UserValves), `__chat_id__`, `__session_id__`, `__message_id__`, `__files__` (from
     `metadata.files`), `__metadata__`, `__event_emitter__`, `__event_call__`, `__task__`,
     `__request__`. Async pipes are awaited; returning an async generator of strings streams.
     `Valves` load from the DB into `self.valves`.
  3. Status events: `{"type": "status", "data": {"description", "done"}}` (matches the router).
     `__event_call__({"type": "confirmation", "data": {"title", "message"}})` waits for the
     user's answer → used for the approve/reject dialog (typed `/approve` stays as fallback).
  4. Attached files arrive as items with an `id` and a `file` object; the stored copy lives at
     `Files.get_file_by_id(id).path` (resolved by `Storage.get_file`), named `<uuid>_<name>`.
     The pipe copies each to a temp folder under its original filename before ingesting.
  5. Downloads: store the file with `Storage.upload_file` + `Files.insert_new_file(FileForm)`
     and link `/api/v1/files/{id}/content` in the reply (also emitted as a `files` event).
  6. Open WebUI runs its own RAG on attachments unless the model's `capabilities.file_context`
     is off, and with `RAG_SYSTEM_CONTEXT=False` it *prepends* its RAG template (ending in
     `</context>`) to the user's message. We set `RAG_SYSTEM_CONTEXT=True`, document turning
     off File Context for the model, and the pipe strips anything up to the last `</context>`.
  7. Task calls (title/tags/follow-ups/queries) go to the selected model — i.e. our pipe —
     with `__task__` set; the pipe returns "" for them, and `start.*` disables those tasks.
  8. Prompts (`/` menu): `POST /api/v1/prompts/create {command, name, content}`; commands are
     stored without the leading `/` (the frontend strips it). Functions:
     `POST /api/v1/functions/create {id, name, content, meta: {description}}`,
     `/id/{id}/update`, `/id/{id}/toggle` (flips), `/id/{id}/toggle/global`; API keys are
     `Bearer sk-…`.
  9. Env vars used by `start.*` (names verified): `OFFLINE_MODE`, `HF_HUB_OFFLINE`,
     `ENABLE_PERSISTENT_CONFIG=False` (env stays authoritative), `ENABLE_WEB_SEARCH`,
     `ENABLE_IMAGE_GENERATION`, `ENABLE_COMMUNITY_SHARING`, `ENABLE_VERSION_UPDATE_CHECK`,
     `ENABLE_OPENAI_API`, `ENABLE_DIRECT_CONNECTIONS`, `OLLAMA_BASE_URL`,
     `RAG_EMBEDDING_ENGINE=ollama`, `RAG_EMBEDDING_MODEL=nomic-embed-text`,
     `RAG_OLLAMA_BASE_URL`, `RAG_SYSTEM_CONTEXT=True`, `ENABLE_TITLE_GENERATION`,
     `ENABLE_TAGS_GENERATION`, `ENABLE_FOLLOW_UP_GENERATION`, `ENABLE_SEARCH_QUERY_GENERATION`,
     `ENABLE_RETRIEVAL_QUERY_GENERATION`, `ENABLE_AUTOCOMPLETE_GENERATION`, `ENABLE_OTEL`,
     `DATA_DIR`; plus `ANONYMIZED_TELEMETRY`, `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK` for
     dependencies. Ollama: `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`,
     `OLLAMA_KEEP_ALIVE=10m`, `OLLAMA_NO_CLOUD=1`.
  10. There is no default-theme env var; light theme is a documented one-time setting.
- Decision: Thin `owui/*.py` function files delegate to a tested `studio.owui` bridge module.
- Spec impact: none (these are the "verify" items of §5.1, §9.5, §12).

## 2026-11-03 — Drop FAISS for NumPy exact search  (Phase 7)
- Context: Running the pipe inside a real Open WebUI 0.13.0 crashed the whole server on the
  first `/ask`: `OMP: Error #15 … libomp.dylib already initialized`. torch (loaded by Open WebUI)
  and faiss-cpu each bundle their own OpenMP runtime; loading both in one process aborts it.
  The only workaround (`KMP_DUPLICATE_LIB_OK=TRUE`) is documented as unsafe and able to give
  incorrect results. The same two-runtime situation is likely on Windows.
- Decision: `VectorIndex` does exact cosine search with NumPy (normalised vectors, one matrix
  product, stable sort): the same results as the FAISS flat inner-product index we used.
  Vectors are stored in `vectors.npz`. An index in the old FAISS layout is cleared on load
  and re-embedded by the next ingest. `faiss-cpu` is removed from the dependencies.
- Why: Correctness and stability in the shared Open WebUI process. RFP and library indexes are
  thousands of chunks, so search is milliseconds. If a library ever reaches hundreds of
  thousands of chunks, an approximate index can be added out of process.
- Spec impact: §2/§3/§7 "FAISS" → exact cosine with NumPy; BUILD_PLAN dependency list updated.

## 2026-11-03 — Open WebUI pipe behaviour  (Phase 7)
- Decision:
  1. `owui/router_pipe.py` and `owui/phi_filter.py` are thin and delegate to the tested
     `studio.owui` bridge (`PipeBridge`, `materialize_files`, `owui_publisher`, `install`).
  2. The confirmation dialog only acts on a literal `True`/`False`. In a real run with no
     browser attached, `__event_call__` returned `{"error": "Client session disconnected."}`
     (truthy), which auto-approved a render. Now the action stays pending and the user is told
     to type `/approve`.
  3. Files the router produces (PPTX, XLSX, research reports) are recorded in
     `session.last_outputs["produced"]` and offered as Open WebUI download links.
  4. Valves: `STUDIO_HOME`, `AUTO_ROUTE`, `AUTO_THRESHOLD`; UserValves:
     `DEFAULT_OPPORTUNITY`. Sessions are keyed per chat id.
  5. `studio owui install` uses the verified API (functions + prompts) and refuses any
     non-localhost URL. `owui/prompts/*.json` are generated from `routes.yaml`
     (`studio owui prompts`), and a test keeps them in sync.
  6. `studio smoke` (used by `smoke_test.*`) runs a synthetic RFP through the router on the real
     models in a throwaway folder. The RFP generator moved into the package
     (`studio.samples`) so release installs can run it.
  7. Scripts: `offline.env` is the single source of the environment for `start.ps1` and
     `start.sh`. Open WebUI binds to 127.0.0.1 and keeps data in `.owui-data/` (gitignored and
     blocked by the private-path guard). CI syntax-checks the `.ps1` (PowerShell parser) and
     `.sh` (`bash -n`) scripts.
- Verified end to end in a real Open WebUI 0.13.0 (API-driven):
  - install via API → model listed
  - upload a PDF and send it → `/ingest`
  - cited `/ask` in 7.5 s
  - `/digest xlsx`, then `/deck` (11 slides)
  - "make the powerpoint" → pending → `/approve`
  - download link serves the PPTX (200, correct MIME type)
  - no non-local network requests in the log
- Spec impact: none.

## 2026-11-03 — VERIFY: agent CLI headless modes  (Phase 8)
- Context: §10 requires checking each CLI before writing its adapter. Installed opencode-ai
  1.19.5 and @anthropic-ai/claude-code 2.1.317 into a scratch npm prefix, plus hermes-agent
  0.19.0 (wheel source read only: the sandbox blocked running third-party code from PyPI).
- Findings:
  1. **OpenCode** headless: `opencode run --agent plan|build --model ollama/<model>
     --dir <workdir> "<prompt>"` (`--format json` exists, `--auto` auto-approves
     permissions). Local Ollama works through a project `opencode.json` provider
     (`@ai-sdk/openai-compatible`, `baseURL http://localhost:11434/v1`, bundled — no npm
     download). The built-in `plan` agent denies edits but *allows bash*, so our config denies
     bash. Network: by default it downloads the models.dev catalogue (6 MB); these env vars
     stop that and other fetches (all verified in the binary, run tested offline):
     `OPENCODE_DISABLE_MODELS_FETCH`, `_AUTOUPDATE`, `_LSP_DOWNLOAD`, `_DEFAULT_PLUGINS`,
     `_EXTERNAL_SKILLS`, `_CLAUDE_CODE` (don't read ~/.claude); config `share: disabled`,
     `autoupdate: false`. Real plan run against qwen3:8b: 42–67 s.
  2. **Claude Code** headless: `claude -p "<prompt>" --model <model> --permission-mode
     plan|acceptEdits --output-format text|json|stream-json`; also `--restricted` (no
     shell/code tools), `--strict-mcp-config`, `--no-session-persistence`. Ollama 0.40 serves
     the Anthropic Messages API (`/v1/messages`), so `ANTHROPIC_BASE_URL=http://localhost:11434`
     + `ANTHROPIC_AUTH_TOKEN=ollama` + `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` +
     `DISABLE_AUTOUPDATER=1` works (real plan run: 28 s). It warns that it doesn't know the
     model's context window (harmless). It is run with an isolated HOME so it can't read the
     user's real Claude credentials/settings.
  3. **Hermes Agent**: scriptable entry point `hermes-agent --query "<prompt>" --model <m>
     --base_url http://localhost:11434/v1 --api_key ollama --max_turns N
     --enabled_toolsets file` (python-fire flags). It has no read-only mode (its "safe"
     toolset includes web access), and a live run could not be verified here → shipped
     **disabled** in `agents.yaml` with these source-derived flags, to enable after testing.
  4. With qwen3:8b, both agents often fail to use their file tools and ask for clarification:
     agent runs on this hardware are slow and of limited quality (warned in chat).
- Decision:
  - The **plan step always runs in a throwaway copy** of the sandbox (discarded after), so
    even agents without a true read-only mode can't change anything while planning.
  - **Apply** runs in a fresh working copy. The diff is shown, and changed files are copied
    back to the opportunity only after a second approval. A changed `deck.json` must still
    validate as a `Deck`.
  - Shell access is denied by default (opencode `bash: deny`, Claude Code `--restricted`); a
    user can relax this in `agents.yaml`.
  - Each run gets an isolated HOME/USERPROFILE inside the sandbox and an allowlisted
    environment (no inherited API keys or secrets).
- Spec impact: §10.1 flags replaced by the verified ones; Hermes disabled by default.
