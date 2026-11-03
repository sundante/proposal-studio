# Proposal Studio — Project Spec (v1)

> This file is the single source of truth for building Proposal Studio. Keep it in the repo root.
> Coding agents: read this file at the start of every session. Do not re-plan what is decided here.
> When something here conflicts with the installed version of a tool, verify against the tool's
> own `--help` / docs, follow the tool, and record the deviation in `vibes/DECISIONS.md`.

---

## 0. Open-source project

Proposal Studio is a **public open-source project on GitHub**. It is built on a development machine
with synthetic data and installed on target machines by downloading a GitHub Release. See §16 for
repository, licensing, CI and release requirements. The project is generic: no employer names,
client names, proprietary templates or real proposal content ever enter the repo. "Firm template"
below means *whatever template the user drops into `templates/` locally*.

## 1. What we are building

A **fully local, fully offline** proposal workbench for pre-sales Solutions Architects in regulated
industries (healthcare first — HIPAA/HITRUST/FHIR-aware defaults). It turns RFP documents into an AI-practice proposal deck (PPTX on the firm's
master template), answers questions about RFPs, researches over a local reference library, and can
hand tasks to local coding agents. All from one chat UI: **Open WebUI**.

### Non-negotiable constraints

| Constraint | Consequence for the design |
|---|---|
| Reference target: **Windows 11 laptop, 16 GB RAM, Intel iGPU, CPU-only inference** (must also run on macOS/Linux) | One LLM loaded at a time. Short prompts. Small, bounded LLM calls. Heavy lifting in plain Python. |
| **No admin rights, no Docker, no WSL** | Python (user install / venv) + Node (user install) only. No SearXNG, no containers. |
| **No internet at runtime** | Internet allowed only at setup time (pip, npm, `ollama pull`). Everything else must work with the network cable pulled. |
| **US healthcare clients; confidential RFPs** | Nothing leaves the machine. Telemetry off everywhere. Block cloud models. Warn on possible PHI in uploads. |
| **Open-source models via Ollama only** | Default models: `qwen3:8b` (worker), `qwen3:4b` (router/classifier), `nomic-embed-text` (embeddings). All configurable. |

### Design principle

**The router is code, not an agent.** Deterministic Python decides the route. LLMs are called only
for narrow, schema-constrained jobs (extract, classify, tailor, answer). Formatting is never done by
an LLM. Agent CLIs (Claude Code, OpenCode, Hermes Agent) are an *optional route* for file/code
tasks inside a sandbox, not the backbone.

---

## 2. Architecture

```
Open WebUI (browser, localhost:8080, offline mode, light theme)
 │
 ├── "Proposal Studio" model  ──►  owui/router_pipe.py   (Open WebUI Pipe function)
 │                                     │  parses /commands, else auto-routes
 │                                     ▼
 │                               studio core (Python package `studio`, installed into the
 │                               SAME venv as Open WebUI so the pipe can `import studio`)
 │                                 ├── router      (commands + auto classifier)
 │                                 ├── ingest      (pdf/docx/xlsx/pptx/txt → sections)
 │                                 ├── rag         (NumPy cosine + nomic-embed-text, cited answers)
 │                                 ├── digest      (RFP → digest.json)
 │                                 ├── blocks      (harvest + block library)
 │                                 ├── deck        (storyline + slide schemas + writer)
 │                                 ├── render      (python-pptx on firm template, NO LLM)
 │                                 ├── research    (offline multi-step research over library)
 │                                 └── llm         (Ollama client, structured output, guards)
 │
 └── "Agents" models (manifold) ──► owui/agents_pipe.py
                                       │  one dropdown entry per agent in config/agents.yaml
                                       ▼
                                 studio.agents  (adapters → headless CLI subprocess,
                                                 sandboxed to workspace/<opp>/, two-phase approval)
                                       │
                                       ▼
                    Ollama (localhost:11434) — OLLAMA_MAX_LOADED_MODELS=1
```

Open WebUI's own built-in RAG/knowledge features stay available for casual chat, but **all
proposal work goes through the `studio` package**, so behaviour is testable outside the UI.

---

## 3. Repository layout

```
proposal-studio/
├── CLAUDE.md / AGENTS.md    # short pointers for coding agents (same content)
├── vibes/                   # non-functional project docs (planning, tracking)
│   ├── PROJECT_SPEC.md      # this file
│   ├── BUILD_PLAN.md        # phases
│   ├── DECISIONS.md         # deviations + decisions log (append-only)
│   ├── PROGRESS.md          # phase checklist, updated at end of each phase
│   ├── START_HERE.md        # build-kit setup notes
│   └── status.md            # narrative summary of work done
├── pyproject.toml           # package `studio`, python >=3.11
├── config/
│   ├── models.yaml          # model registry per role
│   ├── routes.yaml          # commands, aliases, auto-route keywords, thresholds
│   ├── agents.yaml          # agent CLI adapters (command templates)
│   ├── storyline.yaml       # fixed deck spine + optional slides
│   └── layout_map.yaml      # slide_type → template layout + placeholder mapping
├── src/studio/
│   ├── __init__.py
│   ├── config.py            # load/validate YAML (pydantic), env overrides
│   ├── models.py            # shared pydantic models (Cite, …)
│   ├── llm.py               # Ollama client wrapper
│   ├── guards.py            # cloud-model block, PHI scan, path sandbox
│   ├── session.py           # per-chat state (active opportunity, last outputs)
│   ├── router.py
│   ├── ingest.py
│   ├── rag.py
│   ├── digest.py
│   ├── blocks.py
│   ├── deck/
│   │   ├── schemas.py       # pydantic models per slide type
│   │   ├── storyline.py
│   │   └── writer.py
│   ├── render/
│   │   ├── inspect_template.py
│   │   └── renderer.py
│   ├── research.py
│   ├── agents/
│   │   ├── base.py
│   │   └── adapters.py
│   └── cli.py               # `studio` CLI mirroring every chat command (for testing/debug)
├── owui/
│   ├── router_pipe.py       # paste/import into Open WebUI → Functions
│   ├── agents_pipe.py
│   ├── phi_filter.py        # optional inlet filter
│   └── prompts/             # Open WebUI "Prompts" (slash-command shortcuts) as JSON for import
├── templates/               # firm template goes here (gitignored) + a neutral sample template
├── library/                 # gitignored content
│   ├── proposals/           # past proposals & decks (input to /harvest and /research)
│   ├── reference/           # HIPAA/HITRUST/FHIR/CMS docs, whitepapers, vendor docs
│   └── blocks/              # harvested reusable blocks (YAML/JSON, human-editable)
├── workspace/               # gitignored; one folder per opportunity
│   └── <opp-id>/
│       ├── input/           # RFP files
│       ├── index/           # vector index for this RFP
│       ├── digest.json
│       ├── outline.json
│       ├── deck.json
│       ├── research/        # research reports (markdown)
│       ├── agent/           # agent sandbox root
│       └── out/             # rendered PPTX files, versioned
├── scripts/
│   ├── setup.ps1            # user-level install, no admin
│   ├── start.ps1            # sets env vars, starts Ollama check + Open WebUI
│   └── smoke_test.ps1
└── tests/                   # pytest; uses a FakeLLM, never needs Ollama
```

Everything under `library/`, `workspace/` and `templates/<firm>` is **gitignored**. Client data
must never be committed.

---

## 4. Configuration (editable from chat)

### 4.1 `config/models.yaml`
```yaml
ollama_url: http://localhost:11434
roles:
  router:   { model: qwen3:4b,  num_ctx: 4096,  temperature: 0.0 }
  worker:   { model: qwen3:8b,  num_ctx: 16384, temperature: 0.3 }
  embed:    { model: nomic-embed-text }
keep_alive: 10m
block_cloud_models: true      # reject any model name containing ":cloud" or "-cloud"
think: false                  # disable qwen3 thinking by default (speed); per-route override allowed
```

### 4.2 Runtime configuration from the chat
Two mechanisms, both required:
1. **Open WebUI Valves** on each pipe (admin Valves for paths/URLs; UserValves for per-user
   preferences like default opportunity, auto-route on/off, verbosity). This is the native UI.
2. **`/config` command**:
   - `/config` → show the effective config (models, thresholds, active opp, agent list)
   - `/config set worker.model qwen3:4b` → change at runtime (persisted to a user override file
     `config/overrides.yaml`, never editing the base YAML)
   - `/config reset`
   - Validate every change with the pydantic schema; reject unknown keys and cloud models.

---

## 5. Router

### 5.1 Commands (v1)

| Command | Route | What it does |
|---|---|---|
| `/help` | meta | List commands with one-line descriptions and examples |
| `/new <opp-id> [title]` | session | Create `workspace/<opp-id>/`, make it the active opportunity |
| `/use <opp-id>` | session | Switch active opportunity; `/use` alone lists them |
| `/status` | session | Active opp, files ingested, digest/deck/render status, loaded model |
| `/ingest` | ingest | Ingest files attached to the message (or `input/`) into the active opp; build index |
| `/ask <question>` | rag | Answer from the active RFP with section/page citations; say "not found in the RFP" when absent |
| `/digest` | digest | Build/refresh `digest.json`; show a readable summary |
| `/harvest [path]` | blocks | Extract reusable blocks from `library/proposals/` into `library/blocks/` |
| `/blocks [query]` | blocks | Search/list blocks by tag or text |
| `/outline` | deck | Build `outline.json` from storyline + digest: which optional slides are on, and why |
| `/toggle <slide_id> on\|off` | deck | Change optional slides in the outline |
| `/deck [slide_id]` | deck | Write `deck.json` (all slides, or one slide) by tailoring blocks to the digest |
| `/edit <slide_id> <instruction>` | deck | Revise one slide's JSON; show a before/after diff |
| `/render` | render | Build PPTX from `deck.json` on the firm template; return file + QA report |
| `/research <question>` | research | Offline multi-step research over `library/` (+ active RFP); saves cited markdown report |
| `/agent <name> <task>` | agents | Run an agent CLI in the opp sandbox (two-phase approval, see §10) |
| `/config ...` | meta | See §4.2 |

Aliases live in `routes.yaml` (e.g., `/q` → `/ask`, `/r` → `/render`).

**Open WebUI "/" conflict:** Open WebUI uses `/` to open its saved-Prompts menu. Ship one Open WebUI
Prompt per command in `owui/prompts/` (command `/deck` inserts the text `/deck `), so typing `/`
shows our commands with autocomplete, and the inserted text is then parsed by `router_pipe`.
Verify the Prompt import format for the installed Open WebUI version.

### 5.2 Auto-routing (no command given)
1. **Rules first** (no LLM): attachments present + no text → `/ingest`; question mark + active opp
   with index → `/ask`; keywords from `routes.yaml` (e.g., "render", "pptx", "slide 4") → route.
2. **Classifier fallback**: `router` model with a JSON-schema-constrained output
   `{route, confidence, args}`; prompt under ~600 tokens; few-shot examples from `routes.yaml`.
3. If `confidence < routes.auto_threshold` (default 0.7) → ask a one-line clarifying question
   listing the 2 most likely commands. Never guess on routes that write files (`/render`,
   `/agent`, `/harvest`): those require an explicit command or a confirmation.
4. Always print the chosen route in a status line (`→ routed to /ask (rules)`), so routing is
   transparent and correctable.

### 5.3 Session state
Keyed by Open WebUI chat id (fallback: user id). Stores active opp and last outputs. Persisted as
JSON under `workspace/.sessions/`. Survives Open WebUI restarts.

---

## 6. LLM client (`studio/llm.py`)

- Talk to Ollama's native API (`/api/chat`, `/api/embed`) with `httpx`. No LangChain required;
  LangGraph is optional and only if it clearly simplifies `research.py`.
- `generate_structured(role, messages, schema: type[BaseModel])` → uses Ollama's `format` parameter
  with the pydantic JSON schema, then validates with pydantic; on failure retry up to 2 times with
  the validation error appended; then raise a clear error.
- `generate_text(role, messages, stream=True)` for chat answers.
- `embed(texts)` batched.
- Guards: refuse cloud models (`guards.py`), cap `num_ctx` per role, timeouts, and a clear
  user-facing message when Ollama isn't running or the model isn't pulled (`ollama pull <model>`).
- A **single-flight lock**: only one generation at a time (16 GB machine). Queue others, emit
  "waiting for model…" status.
- All callers depend on an `LLMClient` Protocol (see vibes/DECISIONS.md), so `FakeLLM` can stand in.
- `FakeLLM` in tests returns canned structured outputs keyed by schema name.

---

## 7. Ingest + RAG

- Supported: PDF (`pymupdf`), DOCX (`python-docx`), XLSX (`openpyxl`, for requirement matrices),
  PPTX (`python-pptx`, for past decks), TXT/MD.
- Section-aware chunking: keep heading path + page number on every chunk (`"3.2 Scope > Data
  Integration", p.14`). Target ~800 tokens, 100 overlap. Tables → row-wise text with headers.
- Index per opportunity in `workspace/<opp>/index/` (exact cosine with NumPy; FAISS was dropped, see DECISIONS.md). Library indexes in
  `library/.index/{proposals,reference}`. Incremental: hash files, skip unchanged.
- `/ask`: retrieve top-k (default 6), answer with the worker model, **every claim cites
  `[section, p.N]`**, and say clearly when the RFP doesn't cover the question.
- PHI scan on ingest (`guards.py`): regex for SSN, MRN-like IDs, DOB patterns, phone + name combos.
  On hit: warn in chat, list the file/page, continue only after confirmation (RFPs should not
  contain PHI).

---

## 8. RFP digest (`digest.json`)

Map-reduce over sections with the worker model, schema-constrained per section, then merge and
de-duplicate in Python.

```
Digest:
  opportunity: {client, title, due_date, submission_format, page_or_slide_limits}
  business_problems: [ {statement, evidence:[cite]} ]
  technical_problems: [ {statement, evidence:[cite]} ]
  current_state: [ {item, evidence} ]          # feeds "Before"
  desired_outcomes: [ {item, evidence} ]       # feeds "After"
  requirements: [ {id, text, type: functional|nonfunctional|compliance, mandatory:bool, cite} ]
  evaluation_criteria: [ {criterion, weight?, cite} ]
  compliance: [ {framework: HIPAA|HITRUST|SOC2|FHIR|CMS-0057|..., detail, cite} ]
  systems_mentioned: [ {name, role} ]          # EHRs, clouds, payers' platforms
  risks_and_red_flags: [ {item, cite} ]
  open_questions: [ str ]                      # clarification questions for the client
```
`/digest` shows a readable summary in chat and offers to export a requirements compliance matrix
as XLSX (optional, nice-to-have).

---

## 9. Blocks, storyline, deck writer, renderer

### 9.1 Block library (`/harvest`)
- Input: past proposals/decks in `library/proposals/`.
- For each slide/section, the worker model classifies and extracts **reusable, client-neutral**
  blocks: `{id, slide_type, title, body_points[], tags[], capability, source_file, source_ref}`.
- **Anonymise**: strip client names, people, dates, figures tied to a client; replace with
  placeholders like `{{client}}`. Flag anything uncertain for review.
- Write each block as a human-editable YAML file in `library/blocks/<slide_type>/`. The human is
  the curator; harvest never overwrites edited blocks (track `edited: true`).

### 9.2 Storyline (`config/storyline.yaml`)
Fixed spine with optional slides; each slide has `id`, `slide_type`, `required`, `include_if`
(simple rules over the digest, e.g., `compliance contains HITRUST`), and `max_items`.

Default spine:
1. `title` — cover (client, opportunity, date)
2. `understanding` — our understanding of your business & technical challenges
3. `before_after` — current state → future state with us
4. `solution_architecture` — AI solution architecture (layers / components / flows, text-based in v1)
5. `ai_enablement` — AI enablement advantages
6. `platform` — complete AI platform: development, MLOps/LLMOps, observability, governance
7. `governance` — responsible AI, security & HIPAA/HITRUST alignment (optional, rule-driven)
8. `maturity` — maturing the client on AI (roadmap / maturity model)
9. `practice_leadership` — AI as a practice: leadership & insights
10. `why_us` — differentiators (optional)
11. `next_steps` — engagement plan / timeline (optional)

### 9.3 Slide schemas (`deck/schemas.py`)
One pydantic model per `slide_type` with **hard character limits per field** derived from the
template layout (configurable in `layout_map.yaml`), e.g. title ≤ 70 chars, bullet ≤ 110 chars,
3–5 bullets. Every slide also has `speaker_notes` and `sources: [block_ids + digest cites]`.

### 9.4 Writer (`/deck`)
For each slide in the outline:
1. Retrieve 2–4 candidate blocks for the slide type (tag match + embedding similarity to the
   digest's relevant fields).
2. Prompt the worker: "tailor these vetted blocks to this client's pains; keep claims within the
   blocks; do not invent metrics, client names or certifications". Output = that slide's schema.
3. Validate; if over the limits, one automatic "shorten" retry; then truncate safely and flag.
4. Write `deck.json` with per-slide provenance.
One slide per LLM call, so a single slide can be regenerated (`/deck <slide_id>`, `/edit`).

### 9.5 Renderer (`/render`) — no LLM
- `inspect_template.py`: dump every layout name and placeholder (idx, type, name, size) of the
  firm template to `templates/<name>.layouts.json`, to help write `layout_map.yaml`.
- `.potx` handling: python-pptx may refuse `.potx`; support it by copying the file and patching
  the main content type in `[Content_Types].xml` to the presentation type, or instruct the user to
  "Save As .pptx" once. Verify which works and record in `vibes/DECISIONS.md`.
- Render each slide into its mapped layout/placeholders; remove the template's sample slides;
  write `out/<opp>-v<N>.pptx` (never overwrite).
- Text-based architecture slide in v1: layered boxes drawn with python-pptx shapes from a simple
  `layers → components` structure. Cloud icons are out of scope for v1 (see §13).
- **QA report** returned in chat: slide count, empty placeholders, fields truncated, char-limit
  warnings, missing provenance. Also output the file to the chat for download (Open WebUI file
  attachment / link to a static path; verify the supported mechanism).

---

## 10. Agents route (Claude Code, OpenCode, Hermes Agent; extensible)

### 10.1 `config/agents.yaml`
```yaml
sandbox_root: workspace/{opp}/agent
default_timeout_s: 900
agents:
  opencode:
    label: "OpenCode (local)"
    plan_cmd:  ["opencode", "run", "--model", "ollama/{model}", "{prompt}"]   # VERIFY flags
    apply_cmd: ["opencode", "run", "--model", "ollama/{model}", "{prompt}"]
    env: {}
    model: qwen3:8b
  claude-code:
    label: "Claude Code (via Ollama)"
    plan_cmd:  ["claude", "-p", "{prompt}", "--model", "{model}", "--permission-mode", "plan",
                "--output-format", "stream-json"]                               # VERIFY flags
    apply_cmd: ["claude", "-p", "{prompt}", "--model", "{model}",
                "--permission-mode", "acceptEdits", "--output-format", "stream-json"]
    env:
      ANTHROPIC_BASE_URL: http://localhost:11434
      ANTHROPIC_AUTH_TOKEN: ollama
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"
    model: qwen3:8b
  hermes:
    label: "Hermes Agent (local)"
    plan_cmd:  ["hermes", "..."]        # VERIFY: find the headless/non-interactive mode
    apply_cmd: ["hermes", "..."]
    env: {}
    model: qwen3:8b
  # deepseek-harness: add here once the exact tool is chosen
```
**All flags marked VERIFY must be checked with each CLI's `--help` before coding the adapter.**
If a CLI has no reliable headless mode, implement the adapter as "not supported headless" with a
clear message, rather than faking it.

### 10.2 Behaviour
- `agents_pipe.py` is a manifold Pipe: one Open WebUI model per enabled agent
  ("Agent · OpenCode", …). `/agent <name> <task>` from the Proposal Studio model calls the same
  code.
- **Sandbox**: `cwd` = `workspace/<opp>/agent/`; files the task needs are *copied* in
  (e.g., `deck.json`, `digest.json`); results are copied back only on approval. Reject any task
  path outside the sandbox. Strip env to an allowlist plus the agent's `env`.
- **Two-phase approval**:
  1. Run `plan_cmd` (read-only/plan mode where supported) → show the plan and proposed commands.
  2. Ask for confirmation in chat (Open WebUI `__event_call__` confirmation dialog; fallback:
     reply `/approve` or `/reject`).
  3. On approve, run `apply_cmd`; stream output through `__event_emitter__`; show a diff of
     changed files.
- Timeouts, kill on cancel, capture stdout/stderr to `workspace/<opp>/agent/logs/`.
- Windows: use `asyncio.create_subprocess_exec` (Proactor loop) or a thread with `subprocess.Popen`;
  resolve `.cmd` shims for npm-installed CLIs (`opencode.cmd`, `claude.cmd`).
- Warn the user in chat that agent runs on this laptop are slow (minutes per step).

---

## 11. Research route (`/research`, offline)

Multi-step research over `library/` (+ active RFP index), no web:
1. Decompose the question into 3–5 sub-questions (router model, structured).
2. For each: multi-query retrieval (original + 2 rephrasings) over proposals, reference and the RFP.
3. Draft findings per sub-question with citations `[file, page/slide]`.
4. Gap check: one extra retrieval round for sub-questions with weak evidence.
5. Synthesize a report: summary, findings, implications for this RFP, gaps ("not covered in the
   library"). Save `workspace/<opp>/research/<slug>.md` and show it in chat.
Hard cap on LLM calls per run (configurable, default 12) and visible progress via status events.

---

## 12. Open WebUI integration & setup

### 12.1 Install (no admin)
- Python 3.11 venv (user-level): `py -3.11 -m venv .venv`; `pip install open-webui`; `pip install -e .`
  (installs `studio` into the same venv, so pipes can import it).
- Node (user-level, e.g., a portable zip or nvm-windows user install) for `opencode` and `claude`.
- Ollama: user install; `ollama pull qwen3:8b qwen3:4b nomic-embed-text`.
- `setup.ps1` does all of this idempotently and prints what it could not do.

### 12.2 Offline & privacy configuration (`start.ps1` sets these)
- Open WebUI: offline mode on, web search off, image generation off, community sharing off,
  telemetry/analytics off where the installed version exposes it; RAG embeddings via Ollama
  (`nomic-embed-text`) so no Hugging Face model downloads; `HF_HUB_OFFLINE=1`. **Verify exact env
  var names against the installed Open WebUI version** and record in `vibes/DECISIONS.md`.
- Ollama: `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=10m`; plus
  any setting that disables cloud models, if available.
- Claude Code: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` (in the adapter env).
- OpenCode: disable sharing/telemetry features per its docs.
- Default UI theme: light.

### 12.3 Functions to install in Open WebUI
- `router_pipe.py` → model "Proposal Studio" (Valves: workspace path, library path, auto-route
  on/off, threshold).
- `agents_pipe.py` → models "Agent · …" per enabled agent.
- `phi_filter.py` (optional inlet filter) → warns on PHI patterns in typed text.
- Import `owui/prompts/*.json` for slash-command autocomplete.
- A short `INSTALL_OPENWEBUI.md` with screenshots-free step-by-step instructions.

### 12.4 UX rules in chat
- Every long step emits status events ("Embedding 214 chunks…", "Writing slide 4/9…").
- Every answer ends with the next obvious command (e.g., after `/digest`: "Next: `/outline`").
- Errors are one plain sentence plus the fix (e.g., "Model qwen3:8b isn't pulled. Run
  `ollama pull qwen3:8b`.").

---

## 13. Out of scope for v1 (keep extension points)
- Cloud-icon architecture diagrams (`/diagram`, using official Azure/AWS/GCP icon sets placed
  locally) — v2.
- Web research — permanently off unless policy changes; keep `research.py` source-pluggable.
- Multi-user, auth hardening, GPU tuning.

---

## 14. Quality bar & tests
- `pytest` passes offline with `FakeLLM`; no test needs Ollama, internet, or the firm template
  (use the neutral sample template in `templates/sample/`).
- Golden tests: sample RFP (synthetic, in `tests/fixtures/`) → digest schema-valid; sample
  `deck.json` → PPTX renders with zero empty placeholders.
- Router tests: every command parses; auto-route rules; low confidence → clarification.
- Sandbox tests: path traversal rejected; cloud model names rejected.
- `studio` CLI mirrors every chat command so each route can be tested without Open WebUI.
- Type hints throughout; `ruff` clean.

## 15. Performance budget (16 GB, CPU)
- Router decision: < 1 s with rules; < 15 s with classifier.
- `/ask`: first token < 60 s.
- `/deck` full: ~10–20 min acceptable, with per-slide progress; single slide < 2 min.
- `/render`: < 10 s.
- Open WebUI + studio idle RAM < 2 GB (excluding the loaded model).

---

## 16. Repository, licensing, CI and releases

### 16.1 Repository
- GitHub repo `proposal-studio` (name changeable), default branch `main`, protected; work happens on
  `phase/<n>-<slug>` branches merged by PR (squash). Conventional Commits (`feat:`, `fix:`, `docs:`,
  `test:`, `chore:`, `ci:`).
- Required files: `README.md`, `LICENSE` (Apache-2.0), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`
  (Contributor Covenant), `SECURITY.md` (how to report issues; states the no-telemetry,
  local-only design), `CHANGELOG.md` (Keep a Changelog), `docs/` (install, commands, config,
  templates, agents, troubleshooting, privacy).
- `.github/`: `ISSUE_TEMPLATE/bug_report.yml`, `feature_request.yml`, `PULL_REQUEST_TEMPLATE.md`
  (checklist includes "no client/proprietary data added"), `dependabot.yml` (pip + github-actions,
  monthly).
- `.gitignore` covers `library/`, `workspace/`, `templates/*` except `templates/sample/`,
  `config/overrides.yaml`, `.venv/`, indexes, logs, `*.pptx` outside fixtures.
- A pre-commit config (ruff, end-of-file, trailing whitespace, check-added-large-files, and a
  simple guard that blocks committing files under `library/` or `workspace/`).

### 16.2 CI (`.github/workflows/ci.yml`)
- On push/PR: matrix `windows-latest` + `ubuntu-latest`, Python 3.11 and 3.12; `pip install -e .[dev]`;
  `ruff check`; `ruff format --check`; `pytest -q`. No Ollama, no network beyond pip.
- A job that runs `studio render` on the sample deck fixture and uploads the PPTX as a build artifact,
  so every PR shows a real rendered deck.

### 16.3 Releases (`.github/workflows/release.yml`)
- On tag `v*.*.*`: build sdist + wheel, and a **Windows bundle zip**
  `proposal-studio-<version>-windows.zip` containing the source, `scripts/*.ps1`, `owui/`, `config/`,
  `templates/sample/`, docs; attach all to a GitHub Release with notes from `CHANGELOG.md`.
- Versioning: SemVer, starting `0.1.0`. `studio --version` reports it.

### 16.4 Install from GitHub (end-user path, documented in README and docs/install.md)
1. Download the latest Release zip (or `git clone`) while online.
2. Run `scripts\setup.ps1` (no admin): venv, pip installs, `pip install -e .`, `ollama pull` of the
   default models, optional npm user installs of agent CLIs.
3. Go offline. Run `scripts\start.ps1`, open `http://localhost:8080`, follow docs/install.md to add
   the functions and prompts (or use the automated import if the Open WebUI version supports it).
4. Upgrade = download the new zip, re-run `setup.ps1`; `library/`, `workspace/`, `templates/` and
   `config/overrides.yaml` are preserved.

### 16.5 Open-source hygiene
- All sample/fixture content is synthetic and labelled as such ("Acme Health Plan", "Example
  Hospital"). No real company, person or RFP text.
- The sample template is original and generated in code (no copied brand assets).
- No telemetry of any kind in the project's own code.
