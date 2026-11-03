# Privacy and data handling

Proposal Studio is designed for confidential RFPs in regulated industries (US healthcare
first). **Nothing leaves the machine at runtime.**

## What is local

- **Models:** Ollama on `localhost:11434` only. Cloud models (`:cloud`, `-cloud`) are refused,
  and `OLLAMA_NO_CLOUD=1` turns off Ollama's own cloud features.
- **UI:** Open WebUI bound to `127.0.0.1:8080`, with `OFFLINE_MODE=true`. Web search, image
  generation, community sharing, OpenAI connections, update checks and OpenTelemetry are all off
  (`scripts/offline.env`).
- **Embeddings:** `nomic-embed-text` through Ollama, for both Proposal Studio and Open WebUI's
  own RAG, so no Hugging Face downloads (`HF_HUB_OFFLINE=1`).
- **Agents:** local CLIs pointed at local Ollama, with network-fetching features switched off.
  Runs are sandboxed, with an isolated HOME, no inherited API keys, and shell access denied by
  default.
- **Telemetry:** none in Proposal Studio's code; dependencies are told not to send any
  (`ANONYMIZED_TELEMETRY=False`, `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`).

Internet is used only during **setup** (pip packages, `ollama pull`, optional npm agent CLIs).

## Where data lives (all gitignored)

| Folder | Contents |
|---|---|
| `workspace/<opp>/` | RFP files, index, digest, outline, deck, renders, research reports, agent sandbox |
| `library/` | Past proposals, reference documents, harvested blocks, library indexes |
| `templates/` | Your own templates (only `templates/sample/` is in the repo) |
| `.owui-data/` | Open WebUI's database (chats, users, uploaded files) |
| `config/overrides.yaml` | Your settings |

A pre-commit hook and a CI check refuse to commit any of these.

## Safeguards

- **PHI:** files are scanned for SSNs, MRN-like ids, dates of birth, and names with phone
  numbers. If anything turns up, nothing is ingested until you confirm. The optional Open WebUI
  filter warns about (or blocks) PHI in typed messages. These are heuristics, not
  de-identification: RFPs shouldn't contain PHI in the first place.
- **Harvested blocks** are anonymised twice. The model replaces client names, and Python then
  replaces names, dates and amounts with `{{client}}`, `{{date}}` and `{{amount}}`, drops emails
  and phone numbers, and flags any remaining figures for review. You curate the YAML before
  blocks are used.
- **Deck guards:** invented figures or certifications, claims about the client that aren't in
  the RFP, and placeholder dates filled with unrelated values are all flagged for review.

## Checklist before using real documents

- [ ] Your organisation permits these tools (Open WebUI, Ollama, the models) on this machine.
- [ ] `scripts/start.*` is used, so the offline environment is applied.
- [ ] Open WebUI's **File Context** is off for the Proposal Studio model.
- [ ] The Ollama tray app isn't overriding the `OLLAMA_*` settings (see troubleshooting).
- [ ] Real client files stay in `workspace/` / `library/`, never in the repository.
