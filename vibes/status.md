# Proposal Studio — Status

_Last updated: 2026-11-03 · Branch `dev` · 4 of 11 phases done · 122 tests passing_

Proposal Studio is a fully local, offline proposal workbench. It turns RFP documents into an
AI-practice proposal deck on the user's own PowerPoint template, answers RFP questions with
citations, and researches over a local library. It runs on Open WebUI + Ollama + the Python
package `studio`. The design is in [PROJECT_SPEC.md](PROJECT_SPEC.md), the phases are in
[BUILD_PLAN.md](BUILD_PLAN.md), the checklist is in [PROGRESS.md](PROGRESS.md), and the
reasoning behind each deviation is in [DECISIONS.md](DECISIONS.md).

## At a glance

| Phase | What | Status |
|---|---|---|
| 0 | Bootstrap: repo, OSS files, CI, config, LLM client, guards, CLI | ✅ done |
| 1 | Ingest + RAG + `/ask` | ✅ done |
| 2 | RFP digest (`digest.json`, summary, XLSX matrix) | ✅ done |
| 3 | Template inspector + PPTX renderer (no LLM) | ✅ done |
| 4 | Blocks, storyline, deck writer | ⬜ next |
| 5–10 | Research, router, Open WebUI, agents, hardening, release | ⬜ todo |

What a user can do today, from the command line (there is no chat UI until Phase 7):

```bash
studio doctor                                   # checks Python, config, workspace, Ollama, models
studio new acme-demo "Acme Health Plan AI RFP"  # create an opportunity
studio ingest rfp.pdf addendum.docx             # PHI-scanned, indexed, incremental
studio ask "When are proposals due?"            # cited answer, or "Not found in the RFP."
studio digest --xlsx                            # structured digest + requirements matrix
studio status                                   # files, chunks, digest (stale?), loaded model
studio template inspect templates/firm.potx     # layouts + placeholder idx → firm.layouts.json
studio render --deck tests/fixtures/sample_deck.json --out build/   # PPTX + QA report
studio config set worker.model qwen3:4b         # runtime override; cloud models rejected
```

## Work done

### Phase 0 — Bootstrap
- **Repo and open-source foundations:** src layout, `pyproject.toml`, Apache-2.0 licence,
  README, CONTRIBUTING, Code of Conduct, SECURITY, CHANGELOG, issue and PR templates,
  Dependabot, and pre-commit with a guard that blocks committing `library/`, `workspace/`,
  private templates or `config/overrides.yaml`.
- **CI:** GitHub Actions on Windows and Ubuntu × Python 3.11/3.12, running ruff and pytest.
  It runs on pushes to `dev` and `main`.
- **Config** (`config/*.yaml` → pydantic, `extra="forbid"`): models, routes, agents, storyline,
  layout map and RAG settings. Runtime changes go to `config/overrides.yaml` through dotted keys
  with shorthand (`worker.model` means `models.roles.worker.model`). The project root is
  `$STUDIO_HOME` or the current directory.
- **LLM client** (`studio/llm.py`):
  - the `LLMClient` protocol and `OllamaClient` (httpx, native `/api/chat` and `/api/embed`)
  - JSON-schema structured output with 2 validation retries
  - streaming text and batched embeddings
  - a single-flight lock ("waiting for model…")
  - plain-sentence errors ("Run `ollama pull qwen3:8b`")
- **Guards** (`studio/guards.py`): blocks cloud models (`:cloud`/`-cloud`), sandboxes paths
  (traversal and symlink escapes), and runs a PHI regex scan (SSN, MRN, DOB, phone + name)
  that masks what it reports.

### Phase 1 — Ingest, RAG, `/ask`
- **Ingest** (`studio/ingest.py`) for PDF, DOCX, XLSX, PPTX, TXT and MD:
  - Every section keeps its heading path and page or slide number, e.g.
    `[3 Scope of Work > 3.2 Compliance, p.2]`.
  - Tables are read row by row with their headers (`ID: R-01; Requirement: …; Mandatory: Yes`).
  - Chunks are ~800 tokens with 100 overlap and never span two sections.
- **PHI safety:** if possible PHI is found, nothing is copied or indexed until the user
  confirms (`--yes`).
- **Index** (`studio/rag.py`):
  - FAISS cosine index per opportunity (and for library collections).
  - Files are hashed, so a re-ingest only re-embeds changed files.
  - Changing the embedding model triggers a rebuild.
  - Index writes are Windows-safe.
- **`/ask`:** the model cites excerpt numbers and Python rewrites them, while streaming, into
  exact `[section, p.N]` labels. When retrieval is weak, it says "Not found in the RFP." without
  calling the LLM.
- **Sessions** (`studio/session.py`): opportunities live under `workspace/<opp>/`. Per-chat
  state is kept in `workspace/.sessions/` and survives restarts.

### Phase 2 — RFP digest
- **`studio/digest.py`**, a map-reduce over the indexed chunks:
  - one schema-constrained call per section group of about 2k tokens
  - the reduce step is plain Python
- **Digest contents:** opportunity facts, business and technical problems, current state and
  desired outcomes, requirements (functional, nonfunctional, compliance; mandatory or not),
  evaluation criteria, compliance frameworks, systems mentioned, risks and red flags, and open
  questions. Every item is cited.
- **Python-side safeguards:**
  - invalid citations are dropped
  - de-duplication by text, then by embeddings
  - citations of merged items are combined
  - requirement ids are checked against the cited table rows
  - conflicting facts (for example, two due dates) are flagged as red flags rather than
    silently picked
- **Outputs:**
  - `digest.json` plus `digest.meta.json`, used for stale detection
  - a Markdown summary
  - an XLSX requirements compliance matrix (`out/<opp>-requirements-vN.xlsx`, never
    overwritten)

### Phase 3 — Template inspector + renderer (no LLM)
- **Slide schemas** (`studio/deck/schemas.py`) for all 11 storyline slide types: title, bullet
  slides, before/after, architecture layers, maturity stages and next steps. Each carries
  speaker notes and sources (provenance). `slide_model()` builds strict, length-limited
  versions as the LLM schema for the Phase 4 deck writer.
- **Template inspector:** `studio template inspect` lists layouts and placeholder idx values
  and writes a `.layouts.json` to help fill `config/layout_map.yaml`. `.potx` files open
  through an in-memory content-type patch (verified).
- **Renderer** (`studio/render/renderer.py`):
  - removes the template's own slides
  - maps each slide type to a layout and its fields to placeholders
  - enforces limits: word-boundary truncation, item trimming
  - deletes unfilled placeholders
  - draws the architecture slide as layered boxes
  - writes the sources into speaker notes
  - saves versioned `<opp>-vN.pptx` files
  - returns a QA report covering errors, truncations, empty placeholders and missing
    provenance
- **Sample template:** an original, neutral 16:9 template generated in code
  (`studio template sample`).
- **Results:** the sample deck renders 11 slides in ~0.03 s with zero QA errors, no shapes off
  the slide, no overlaps and no empty placeholders. CI uploads the rendered deck as an
  artifact.

## Verified on a real model
Local Ollama with qwen3:8b and nomic-embed-text, on the synthetic Acme Health Plan RFP:

| Check | Result |
|---|---|
| `ask` "When are proposals due?" | Correct, cited `[2 Submission Instructions, p.1]`, ~9 s |
| `ask` on an off-topic question | "Not found in the RFP." |
| `ask` "Which requirements are mandatory?" | R-01 and R-02 from the table, cited p.3 |
| Re-ingest of an unchanged file | Skipped, nothing re-embedded |
| `digest` | Due date, 30-slide limit, portal, R-01/R-02 mandatory, R-03 optional, HIPAA/HITRUST/CMS-0057, the 40/30/30 weights, all cited. ~1 min 50 s for 2 section groups |

Problems that real runs exposed and that are now fixed in code:
- The model mis-copied long citation labels. It now cites excerpt numbers and Python adds the
  labels.
- The model stamped the prompt's example id onto every requirement. Ids are now checked
  against the cited table rows.
- PDF table cells lost their spaces. Text is now read per cell box.

## Quality
- **101 offline tests** (no Ollama, no internet, no real template), covering config, guards, the
  LLM client, ingest for every format, the index, answers and citations, sessions, the digest
  and the CLI.
- Tests use `FakeLLM` and a deterministic bag-of-words fake embedder.
- Fixtures are synthetic ("Acme Health Plan") and generated at test time; they're never
  committed.
- ruff lint and format are clean. About 2.9k lines of source and 1.3k lines of tests.

## Process
- Git: only `dev` and `main`. All work is committed and pushed to `dev`, and the maintainer
  promotes it to `main` by hand. There are no phase branches or PRs.
- Docs: non-functional planning and tracking docs live in `vibes/`. Files that tools or GitHub
  expect at the root stay there: README, LICENSE, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT,
  SECURITY, CLAUDE.md, AGENTS.md, `.claude/` and `.github/`.

## Known issues and risks
- `digest` takes ~55 s per section group on Apple silicon. Expect several minutes per group on
  the 16 GB CPU-only Windows target; prompt and output size will be tuned in Phase 9.
- Ingesting one RFP as both PDF and DOCX duplicates excerpts. The docs should recommend one
  format per document.
- Ollama loads the embedding and worker models together unless `OLLAMA_MAX_LOADED_MODELS=1` is
  set; the start scripts will set it in Phase 7.
- `pip install open-webui` is multi-GB (torch), which puts the <2 GB idle RAM budget at risk.
  Revisit in Phase 9.
- Hermes Agent may lack a headless mode on Windows; Phase 8 will likely mark it unsupported.
- CI hasn't yet been observed running on Windows.
- Rendered decks have only been checked structurally. No LibreOffice here, and Quick Look hangs
  headless, so open the CI `sample-deck` artifact in PowerPoint once to check it by eye.

## Next up — Phase 4
Blocks, storyline and the deck writer:
- `/harvest` reusable, anonymised blocks from past proposals into `library/blocks/`
- `/outline` from `storyline.yaml` plus digest rules
- `/deck` tailors 2–4 vetted blocks per slide into `slide_model()` output, with a shorten retry
  and provenance
- `/edit` with a diff
