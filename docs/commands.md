# Commands

<!-- Generated from config/routes.yaml by `studio docs`. Do not edit by hand. -->

Type these in the chat in `studio ui`, in `studio chat`, or use the
matching `studio <command>` CLI. Plain text works too: questions go to `/ask` once an RFP
is ingested, and other requests are routed automatically. Every reply shows
`→ routed to /x (how)`.

| Command | What it does | Example |
|---|---|---|
| `/help` | List commands with examples | `/help` |
| `/new` | Create an opportunity: /new <opp-id> [title] | `/new acme-2026 Acme Health Plan AI platform` |
| `/use` | Switch opportunity: /use <opp-id> (alone: list) | `/use acme-2026` |
| `/status` | Show active opportunity and pipeline status | `/status` |
| `/ingest` | Ingest attached files (or input/) and build the index | `(attach files) /ingest` |
| `/ask` | Answer from the active RFP with citations: /ask <question> | `/ask Which requirements are mandatory?` |
| `/digest` | Build or refresh the RFP digest: /digest [xlsx] [show] | `/digest xlsx` |
| `/harvest` | Extract blocks from library/proposals: /harvest [client, …] | `/harvest Old Client Inc, Example Hospital` |
| `/blocks` | Search or list blocks: /blocks [query] | `/blocks mlops observability` |
| `/outline` | Decide which storyline slides go in the deck, and why | `/outline` |
| `/toggle` | Turn an optional slide on/off: /toggle <slide_id> on/off | `/toggle why_us off` |
| `/deck` | Write deck.json (all slides or one): /deck [slide_id] | `/deck platform` |
| `/edit` | Revise one slide: /edit <slide_id> <instruction> | `/edit platform shorter, mention FHIR R4` |
| `/render` | Build the PPTX on your template and show a QA report | `/render` |
| `/research` | Offline research over library/: /research <question> | `/research How have we approached prior authorization before?` |
| `/library` | Index the local library: /library index/status | `/library index` |
| `/agent` | Run an agent CLI in the sandbox: /agent <name> <task> | `/agent opencode tighten the bullets in deck.json` |
| `/config` | Show or change config: /config [set <key> <value> / reset] | `/config set worker.model qwen3:4b` |
| `/approve` | Run the action waiting for confirmation | `/approve` |
| `/reject` | Cancel the action waiting for confirmation | `/reject` |

## Aliases

- `/q` → `/ask`
- `/r` → `/render`
- `/d` → `/digest`
- `/h` → `/help`
- `/yes` → `/approve`
- `/no` → `/reject`

## Confirmation

These commands write files, so they never run from plain text without confirmation: `/render`, `/agent`, `/harvest`. Approve in the dialog or with `/approve` (`/yes`), or cancel with `/reject` (`/no`).

## Auto-routing keywords

- `/render`: "render", "pptx", "powerpoint"
- `/deck`: "write the deck", "build the deck", "generate the deck", "draft the slides"
- `/digest`: "digest", "summarise the rfp", "summarize the rfp"
- `/research`: "research"
- `/harvest`: "harvest"

Anything else goes to the router model; below confidence 0.7 you get a one-line clarifying question.
