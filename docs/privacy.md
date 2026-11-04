# Privacy and data handling

Proposal Studio is designed for confidential RFPs in regulated industries (US healthcare
first). **Nothing leaves the machine at runtime.**

## What is local

- **Models:** Ollama on `localhost:11434` only. Cloud models (`:cloud`, `-cloud`) are refused,
  and `OLLAMA_NO_CLOUD=1` turns off Ollama's own cloud features.
- **UI:** the Proposal Studio app (`studio ui`) listens on `127.0.0.1` only and loads nothing from
  the internet (no CDN, fonts or analytics). Each launch has a secret link; the API needs its
  session cookie, and writes also need a custom header, so other web pages can't drive it. It
  reads and writes only inside the project folders you trusted and the Proposal Studio folder
  (library).
- **Embeddings:** `nomic-embed-text` through Ollama, so no Hugging Face downloads
  (`HF_HUB_OFFLINE=1`).
- **Agents:** local CLIs pointed at local Ollama, with network-fetching features switched off.
  Runs are sandboxed, with an isolated HOME, no inherited API keys, and shell access denied by
  default.
- **Telemetry:** none in Proposal Studio's code; dependencies are told not to send any
  (`ANONYMIZED_TELEMETRY=False`, `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`).

Internet is used only during **setup** (pip packages, `ollama pull`, optional npm agent CLIs).

## Where data lives (all gitignored)

| Folder | Contents |
|---|---|
| a project folder (app) or `workspace/<opp>/` (CLI) | RFP files, index, digest, outline, deck, renders, research reports, agent sandbox |
| `library/` | Past proposals, reference documents, harvested blocks, library indexes |
| `templates/` | Your own templates (only `templates/sample/` is in the repo) |
| `config/overrides.yaml` | Your settings |

A pre-commit hook and a CI check refuse to commit any of these.

## Safeguards

- **PHI:** files are scanned for SSNs, MRN-like ids, dates of birth, and names with phone
  numbers. If anything turns up, nothing is ingested until you confirm. The app also warns when
  a typed message looks like it contains PHI. These are heuristics, not
  de-identification: RFPs shouldn't contain PHI in the first place.
- **Harvested blocks** are anonymised twice. The model replaces client names, and Python then
  replaces names, dates and amounts with `{{client}}`, `{{date}}` and `{{amount}}`, drops emails
  and phone numbers, and flags any remaining figures for review. You curate the YAML before
  blocks are used.
- **Deck guards:** invented figures or certifications, claims about the client that aren't in
  the RFP, and placeholder dates filled with unrelated values are all flagged for review.

## Checklist before using real documents

- [ ] Your organisation permits these tools (Proposal Studio, Ollama, the models) on this machine.
- [ ] `scripts/start.*` is used, so the offline environment is applied.
- [ ] Project folders live outside the repository (default: `Documents\Proposal Studio\…`).
- [ ] The Ollama tray app isn't overriding the `OLLAMA_*` settings (see troubleshooting).
- [ ] Real client files stay in your project folders, never in the repository.
