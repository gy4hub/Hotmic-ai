#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${HOTMIC_PYTHON:-$ROOT_DIR/apps/superdirector/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON:-python3}"
fi

echo "[test_all] python: $PYTHON_BIN"
echo "[test_all] validate shared"
"$PYTHON_BIN" "$ROOT_DIR/shared/validate_shared.py" --dir "$ROOT_DIR/shared"

echo "[test_all] validate plugin"
"$PYTHON_BIN" "$ROOT_DIR/scripts/validate_plugin.py"

echo "[test_all] superdirector"
"$PYTHON_BIN" -m pytest "$ROOT_DIR/apps/superdirector/tests" -q

echo "[test_all] hotmic apps"
"$PYTHON_BIN" -m pytest \
  "$ROOT_DIR/apps/review-engine/tests" \
  "$ROOT_DIR/apps/script-creator/tests" \
  "$ROOT_DIR/apps/video-cutter/tests" \
  -q

echo "[test_all] done"
