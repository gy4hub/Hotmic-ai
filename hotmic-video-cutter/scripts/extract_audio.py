#!/usr/bin/env python3
"""
extract_audio.py — Step 1: 从视频中提取音频（16kHz单声道WAV）

用法:
  python extract_audio.py --input video.MOV --output audio.wav
  python extract_audio.py --input video.mp4  # 自动命名为 audio.wav
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path


def extract_audio(input_path: str, output_path: str | None = None) -> str:
    """
    使用FFmpeg从视频中提取16kHz单声道WAV音频。

    Args:
        input_path: 输入视频文件路径（MOV/MP4等）
        output_path: 输出WAV文件路径，None时自动生成

    Returns:
        输出文件的绝对路径

    Raises:
        FileNotFoundError: 输入文件不存在
        RuntimeError: FFmpeg执行失败
    """
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"输入视频文件不存在: {input_path}")

    # 自动生成输出路径
    if output_path is None:
        output_path = input_path.parent / "audio.wav"
    output_path = Path(output_path).resolve()

    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] 正在提取音频: {input_path} → {output_path}")

    # FFmpeg命令：提取16kHz单声道PCM音频
    cmd = [
        "ffmpeg",
        "-y",                    # 覆盖已有文件
        "-i", str(input_path),   # 输入文件
        "-vn",                   # 不含视频流
        "-acodec", "pcm_s16le",  # 16-bit PCM编码
        "-ar", "16000",          # 16kHz采样率（Whisper推荐）
        "-ac", "1",              # 单声道
        str(output_path)
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"FFmpeg执行失败:\n{e.stderr}"
        ) from e
    except FileNotFoundError:
        raise RuntimeError(
            "FFmpeg未安装。请先安装FFmpeg:\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg"
        )

    # 验证输出文件
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"音频提取失败，输出文件为空: {output_path}")

    file_size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"[OK] 音频提取完成: {output_path} ({file_size_mb:.1f}MB)")

    # Groq免费层限制警告
    if file_size_mb > 24:
        print(f"[WARN] 文件大小 {file_size_mb:.1f}MB 接近Groq免费层25MB限制。"
              "可尝试对长视频分段处理。")

    return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="从视频中提取16kHz单声道WAV音频（用于Groq Whisper转录）"
    )
    parser.add_argument("--input", "-i", required=True, help="输入视频文件路径 (MOV, MP4等)")
    parser.add_argument("--output", "-o", default=None, help="输出WAV文件路径（默认: audio.wav）")
    args = parser.parse_args()

    try:
        output = extract_audio(args.input, args.output)
        print(f"[SUCCESS] 输出: {output}")
    except (FileNotFoundError, RuntimeError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
