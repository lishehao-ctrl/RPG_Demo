#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

VENV_PY="$ROOT_DIR/.venv/bin/python"
if [[ -x "$VENV_PY" ]]; then
  PYTHON_CMD="$VENV_PY"
  ENV_LABEL=".venv"
else
  if command -v python >/dev/null 2>&1; then
    PYTHON_CMD="$(command -v python)"
    ENV_LABEL="system/conda"
  else
    echo "[dev.sh] ERROR: no usable python found."
    echo "[dev.sh] Fix: run 'python -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements.txt'"
    exit 1
  fi
fi

echo "[dev.sh] Runtime env: $ENV_LABEL"
echo "[dev.sh] Python path: $PYTHON_CMD"
"$PYTHON_CMD" -V

if ! "$PYTHON_CMD" -m uvicorn --version >/dev/null 2>&1; then
  echo "[dev.sh] ERROR: uvicorn is not installed in selected python."
  if [[ "$ENV_LABEL" == ".venv" ]]; then
    echo "[dev.sh] Fix: source .venv/bin/activate && python -m pip install -r requirements.txt"
  else
    echo "[dev.sh] Fix (quick): python -m pip install -r requirements.txt"
    echo "[dev.sh] Fix (recommended): python -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements.txt"
  fi
  exit 1
fi

exec "$PYTHON_CMD" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
