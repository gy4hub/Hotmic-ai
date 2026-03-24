#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
VENV_DIR="$ROOT_DIR/apps/superdirector/.venv"
VENV_PY="$VENV_DIR/bin/python"

echo "HotMic AI Plugin 安装"
echo "===================="

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
REQUIRED_VERSION="3.11"
if [[ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]]; then
  echo "Python >= $REQUIRED_VERSION required (found $PYTHON_VERSION)"
  exit 1
fi
echo "Python $PYTHON_VERSION"

if command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg found"
else
  echo "FFmpeg not found (video-cutter will remain unavailable until installed)"
fi

"$PYTHON_BIN" "$ROOT_DIR/shared/validate_shared.py" --dir "$ROOT_DIR/shared"
echo "Shared config validated"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Creating superdirector virtualenv..."
  rm -rf "$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_PY" -m pip install --upgrade pip >/dev/null
"$VENV_PY" -m pip install -r "$ROOT_DIR/apps/superdirector/requirements.txt" >/dev/null
echo "superdirector virtualenv ready"

if command -v ffmpeg >/dev/null 2>&1; then
  bash "$ROOT_DIR/apps/video-cutter/scripts/install_deps.sh" >/dev/null 2>&1 || true
  echo "video-cutter deps attempted"
fi

OPTIONAL_VARS=(GROQ_API_KEY FEISHU_APP_SECRET TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID QWEN_API_KEY)
MISSING=()
for name in "${OPTIONAL_VARS[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    MISSING+=("$name")
  fi
done

if [[ "${#MISSING[@]}" -gt 0 ]]; then
  echo "Optional env vars not set: ${MISSING[*]}"
else
  echo "Optional env vars look good"
fi

echo
echo "HotMic AI 安装完成"
echo "启动选题系统: ./scripts/dev_superdirector.sh"
echo "运行测试:     ./scripts/test_all.sh"
