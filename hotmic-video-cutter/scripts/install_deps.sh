#!/bin/bash
# install_deps.sh — 安装 hotmic-video-cutter 所需的 Python 依赖

set -e

echo "=== HotMic video-cutter 依赖安装 ==="

# 检查 Python3
if ! command -v python3 &>/dev/null; then
  echo "[ERROR] Python3 未安装，请先安装 Python 3.8+"
  exit 1
fi

# 检查 FFmpeg
if ! command -v ffmpeg &>/dev/null; then
  echo "[WARN] FFmpeg 未检测到。请手动安装:"
  echo "  macOS:   brew install ffmpeg"
  echo "  Ubuntu:  sudo apt install ffmpeg"
  echo "  Windows: https://ffmpeg.org/download.html"
fi

# 安装 Python 依赖
pip3 install --upgrade \
  groq \
  python-Levenshtein \
  numpy

echo ""
echo "[OK] 依赖安装完成。"
echo "[INFO] 请确保环境变量 GROQ_API_KEY 已设置。"
echo "  export GROQ_API_KEY=your_key_here"
