# Security policy

## Design
Proposal Studio is **local-only**. It sends no telemetry, makes no network calls at runtime
other than to a local Ollama server (`localhost:11434`), and blocks Ollama cloud models
(`:cloud` / `-cloud`). Your RFPs, libraries and workspaces stay on your machine and are
gitignored.

## Reporting a vulnerability
Please report vulnerabilities privately through GitHub's **"Report a vulnerability"** button
(Security tab → Advisories), not in a public issue. Include the steps to reproduce and the
affected version. We aim to acknowledge within 7 days.

Never include real client documents or PHI in a report. Reproduce with synthetic data.

## Supported versions
Only the latest release receives fixes during the 0.x series.
