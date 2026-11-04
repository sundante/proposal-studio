#!/usr/bin/env bash
# End-to-end check on the real local models (needs Ollama running and the models pulled).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export STUDIO_HOME="$ROOT"
"$ROOT/.venv/bin/studio" doctor
"$ROOT/.venv/bin/studio" smoke "$@"
