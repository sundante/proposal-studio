#!/usr/bin/env bash
# Start Proposal Studio: makes sure Ollama runs, then opens the app (http://127.0.0.1:8765, this
# machine only). The app asks which workspace folder to trust and work in.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a
# shellcheck disable=SC1091
source "$ROOT/scripts/offline.env"
set +a
export STUDIO_HOME="$ROOT"

if ! curl -fs http://127.0.0.1:11434/api/version >/dev/null; then
  echo "Starting Ollama (one model at a time, cloud off)…"
  (ollama serve >"${TMPDIR:-/tmp}/proposal-studio-ollama.log" 2>&1 &)
  sleep 3
else
  echo "Ollama is already running (OLLAMA_* settings above only apply if it was started here)."
fi
"$ROOT/.venv/bin/studio" doctor || echo "(doctor reported problems — see above)"
exec "$ROOT/.venv/bin/studio" ui "$@"
