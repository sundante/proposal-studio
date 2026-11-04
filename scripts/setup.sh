#!/usr/bin/env bash
# Proposal Studio setup for macOS/Linux (development). Idempotent; needs internet; no sudo.
# Creates .venv (Python 3.11+), installs studio, pulls the Ollama models.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
problems=()

pick_python() {
  for cand in python3.12 python3.11 python3.13 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver="$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
      case "$ver" in 3.11|3.12|3.13) echo "$cand"; return 0 ;; esac
    fi
  done
  return 1
}

if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null 2>&1; then
    echo "Creating .venv with uv (Python 3.11)…"
    uv venv --python 3.11 .venv || problems+=("could not create .venv with uv")
  elif PY="$(pick_python)"; then
    echo "Creating .venv with $PY…"
    "$PY" -m venv .venv || problems+=("could not create .venv")
  else
    echo "Python 3.11 or newer is required."; exit 1
  fi
fi

pip_install() {
  if command -v uv >/dev/null 2>&1; then uv pip install --python .venv/bin/python "$@";
  else .venv/bin/python -m pip install "$@"; fi
}
echo "Installing studio…"
pip_install -e "$ROOT" || problems+=("pip install studio failed")

if [ "${STUDIO_SKIP_MODELS:-}" = "1" ]; then
  echo "STUDIO_SKIP_MODELS=1: skipping Ollama and model downloads."
elif command -v ollama >/dev/null 2>&1; then
  if ! curl -fs http://127.0.0.1:11434/api/version >/dev/null; then
    echo "Starting Ollama…"; (OLLAMA_NO_CLOUD=1 ollama serve >/dev/null 2>&1 &) ; sleep 3
  fi
  for model in $(.venv/bin/python -c 'from studio.config import load_config; print(" ".join(sorted({r.model for r in load_config().models.roles.values()})))'); do
    echo "ollama pull $model"; ollama pull "$model" || problems+=("ollama pull $model failed")
  done
else
  problems+=("Ollama not found: install it from https://ollama.com (no admin needed), then re-run")
fi

echo
if [ ${#problems[@]} -eq 0 ]; then
  echo "Setup complete. Next: scripts/start.sh (opens Proposal Studio in your browser)"
else
  echo "Setup finished with problems:"; printf '  - %s\n' "${problems[@]}"; exit 1
fi
