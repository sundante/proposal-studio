#!/usr/bin/env bash
# Start Proposal Studio (Open WebUI on http://localhost:8080, bound to this machine only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a
# shellcheck disable=SC1091
source "$ROOT/scripts/offline.env"
set +a
export STUDIO_HOME="$ROOT"
export DATA_DIR="${DATA_DIR:-$ROOT/.owui-data}"
mkdir -p "$DATA_DIR"

if ! curl -fs http://127.0.0.1:11434/api/version >/dev/null; then
  echo "Starting Ollama (one model at a time, cloud off)…"
  (ollama serve >"$DATA_DIR/ollama.log" 2>&1 &)
  sleep 3
else
  echo "Ollama is already running (OLLAMA_* settings above only apply if it was started here)."
fi
"$ROOT/.venv/bin/studio" doctor || echo "(doctor reported problems — see above)"
echo "Open http://localhost:8080 and pick the 'Proposal Studio' model."
exec "$ROOT/.venv/bin/open-webui" serve --host 127.0.0.1 --port 8080
