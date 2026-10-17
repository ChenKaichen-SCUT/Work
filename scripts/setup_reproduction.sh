#!/usr/bin/env bash
# Run from any directory on Linux after installing Python, venv, development
# headers and g++. This creates a fresh environment without changing OS packages.
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_PATH="${VENV_PATH:-$PROJECT_DIR/.venv}"
if [[ -e "$VENV_PATH" ]]; then
  echo "Choose a new VENV_PATH; refusing to alter an existing environment." >&2
  exit 2
fi
"$PYTHON_BIN" -m venv "$VENV_PATH"
"$VENV_PATH/bin/python" -m pip install -r "$PROJECT_DIR/requirements-fm.txt"
printf 'Ready: %s\n' "$VENV_PATH/bin/python"
printf 'Run from %s: .venv/bin/python experiments/fm_reproduce.py --out replay-full --full\n' "$PROJECT_DIR"
