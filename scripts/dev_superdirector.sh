#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/superdirector"
PYTHON_BIN="${HOTMIC_PYTHON:-$APP_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON:-python3}"
fi

cd "$APP_DIR"
exec "$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port 8100
