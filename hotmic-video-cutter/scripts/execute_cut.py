#!/usr/bin/env python3
"""
execute_cut.py — Step 7: 根据cut_decisions.json执行FFmpeg剪辑

读取cut_decisions.json中的保留段落列表，使用FFmpeg的filter_complex
concat滤镜将保留段拼接输出，生成粗剪视频。

用法:
  python execute_cut.py --input video.MOV --decisions cut_decisions.json --output video_cut.mp4
  python execute_cut.py --input video.MOV --decisions cut_decisions.json --output video_cut.mp4 --dry-run
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def build_ffmpeg_command(
    input_path: str,
    keep_segments: list[dict],
    output_path: str,
    video_codec: str = "libx264",
    crf: int = 18
) -> list[str]:
    """
    构建FFmpeg filter_complex命令，将保留段拼接输出。

    Args:
        input_path: 输入视频路径
        keep_segments: 保留段列表（含segment_start/segment_end）
        output_path: 输出视频路径
        video_codec: 视频编码器（默认libx264）
        crf: 视频质量（0-51，越低质量越高，默认18）

    Returns:
        FFmpeg命令列表
    """
    if not keep_segments:
        raise ValueError("保留段列表为空，无法执行剪辑")

    n = len(keep_segments)

    # 构建filter_complex
    filter_parts = []

    # 每个保留段生成trim/atrim
    for i, seg in enumerate(keep_segments):
        start = seg["segment_start"]
        end = seg["segment_end"]

        # 视频流trim
        filter_parts.append(
            f"[0:v]trim=start={start:.4f}:end={end:.4f},"
            f"setpts=PTS-STARTPTS[v{i}]"
        )
        # 音频流atrim
        filter_parts.append(
            f"[0:a]atrim=start={start:.4f}:end={end:.4f},"
            f"asetpts=PTS-STARTPTS[a{i}]"
        )

    # 拼接所有段
    video_inputs = "".join(f"[v{i}]" for i in range(n))
    audio_inputs = "".join(f"[a{i}]" for i in range(n))
    filter_parts.append(
        f"{video_inputs}{audio_inputs}concat=n={n}:v=1:a=1[vout][aout]"
    )

    filter_complex = ";\n".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",                         # 覆盖已有输出
        "-i", input_path,             # 输入
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", video_codec,
        "-preset", "fast",            # 编码速度
        "-crf", str(crf),             # 质量
        "-c:a", "aac",                # 音频编码
        "-b:a", "192k",
        "-movflags", "+faststart",    # 网络优化
        output_path
    ]

    return cmd


def execute_cut(
    input_path: str,
    decisions_path: str,
    output_path: str,
    dry_run: bool = False,
    video_codec: str = "libx264",
    crf: int = 18
) -> str:
    """
    执行视频剪辑。

    Args:
        input_path: 原始视频路径
        decisions_path: cut_decisions.json路径
        output_path: 输出视频路径
        dry_run: 只打印命令，不实际执行
        video_codec: 视频编码器
        crf: 视频质量

    Returns:
        输出视频的绝对路径
    """
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"输入视频不存在: {input_path}")

    # 加载决策
    with open(decisions_path, "r", encoding="utf-8") as f:
        decisions_data = json.load(f)

    decisions = decisions_data.get("decisions", [])
    keep_segments = [d for d in decisions if d["action"] == "keep"]
    delete_segments = [d for d in decisions if d["action"] == "delete"]

    if not keep_segments:
        raise ValueError("没有需要保留的段落，请检查cut_decisions.json")

    print(f"[INFO] 保留段: {len(keep_segments)}, 删除段: {len(delete_segments)}")

    # 计算保留总时长
    keep_duration = sum(s["segment_end"] - s["segment_start"] for s in keep_segments)
    print(f"[INFO] 预计输出时长: {keep_duration:.1f}s")

    # 构建FFmpeg命令
    output_path_str = str(Path(output_path).resolve())
    Path(output_path_str).parent.mkdir(parents=True, exist_ok=True)

    cmd = build_ffmpeg_command(
        str(input_path), keep_segments, output_path_str, video_codec, crf
    )

    if dry_run:
        print("[DRY-RUN] FFmpeg命令预览:")
        print("  " + " ".join(cmd[:4]) + " \\")
        print(f"  -filter_complex '...' \\")
        print("  " + " ".join(cmd[-8:]))
        return output_path_str

    print(f"[INFO] 开始剪辑: {input_path} → {output_path_str}")
    print("[INFO] 这可能需要几分钟，请耐心等待...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        # FFmpeg错误通常在stderr
        raise RuntimeError(
            f"FFmpeg剪辑失败:\n{e.stderr[-2000:]}"  # 只显示最后2000字符
        ) from e
    except FileNotFoundError:
        raise RuntimeError(
            "FFmpeg未安装。请先安装FFmpeg:\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg"
        )

    # 验证输出
    output_file = Path(output_path_str)
    if not output_file.exists() or output_file.stat().st_size == 0:
        raise RuntimeError(f"输出视频为空，剪辑可能失败: {output_path_str}")

    output_size_mb = output_file.stat().st_size / (1024 * 1024)
    print(f"[OK] 剪辑完成: {output_path_str} ({output_size_mb:.1f}MB)")

    return output_path_str


def main():
    parser = argparse.ArgumentParser(
        description="根据cut_decisions.json执行FFmpeg视频剪辑"
    )
    parser.add_argument("--input", "-i", required=True, help="原始视频文件路径")
    parser.add_argument("--decisions", "-d", required=True, help="cut_decisions.json文件路径")
    parser.add_argument("--output", "-o", default="video_cut.mp4", help="输出视频文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印FFmpeg命令，不实际执行")
    parser.add_argument("--codec", default="libx264", help="视频编码器（默认: libx264）")
    parser.add_argument("--crf", type=int, default=18, help="视频质量CRF（0-51，越低越好，默认18）")
    args = parser.parse_args()

    try:
        execute_cut(
            args.input, args.decisions, args.output,
            args.dry_run, args.codec, args.crf
        )
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
