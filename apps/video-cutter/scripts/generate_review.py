#!/usr/bin/env python3
"""
generate_review.py — Step 6: 生成Markdown格式的人工审核报告

整合cut_decisions.json和transcript.json，生成可读性强的审核报告，
供用户在执行剪辑前确认删除决策。

用法:
  python generate_review.py --decisions cut_decisions.json --transcript transcript.json --output cut_report.md
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def seconds_to_timecode(seconds: float) -> str:
    """将秒数转换为 HH:MM:SS.xx 格式。"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"


def generate_review_report(
    decisions_path: str,
    transcript_path: str,
    output_path: str,
    input_video: str | None = None
) -> str:
    """
    生成Markdown审核报告。

    Args:
        decisions_path: cut_decisions.json文件路径
        transcript_path: transcript.json文件路径
        output_path: 输出Markdown文件路径
        input_video: 原始视频文件名（可选，用于报告标题）

    Returns:
        Markdown报告内容
    """
    # 加载数据
    with open(decisions_path, "r", encoding="utf-8") as f:
        decisions_data = json.load(f)
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    decisions = decisions_data.get("decisions", [])
    total_duration = transcript.get("duration", 0)
    full_text = transcript.get("text", "")

    # 统计
    keep_decisions = [d for d in decisions if d["action"] == "keep"]
    delete_decisions = [d for d in decisions if d["action"] == "delete"]
    repeat_deletes = [d for d in delete_decisions if d.get("type") != "silence"]
    silence_deletes = [d for d in delete_decisions if d.get("type") == "silence"]

    # 计算剪掉的总时长
    deleted_duration = sum(d["segment_end"] - d["segment_start"] for d in delete_decisions)
    estimated_output_duration = (total_duration or 0) - deleted_duration

    # 生成报告时间
    report_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 构建Markdown
    lines = []
    lines.append("# HotMic 粗剪审核报告")
    lines.append("")
    lines.append(f"**生成时间**: {report_time}")
    if input_video:
        lines.append(f"**原始视频**: `{input_video}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 摘要
    lines.append("## 📊 剪辑摘要")
    lines.append("")
    lines.append("| 项目 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 原始时长 | {seconds_to_timecode(total_duration or 0)} |")
    lines.append(f"| 预计剪后时长 | {seconds_to_timecode(max(0, estimated_output_duration))} |")
    lines.append(f"| 删减时长 | {seconds_to_timecode(deleted_duration)} |")
    lines.append(f"| 保留段落数 | {len(keep_decisions)} |")
    lines.append(f"| 删除段落数 | {len(delete_decisions)} |")
    lines.append(f"| &nbsp;&nbsp;— 重复段落 | {len(repeat_deletes)} |")
    lines.append(f"| &nbsp;&nbsp;— 过长静音 | {len(silence_deletes)} |")
    lines.append("")

    # 完整转录文本
    lines.append("## 📝 转录全文")
    lines.append("")
    lines.append("> 以下为Groq Whisper转录的完整文字（供参考）")
    lines.append("")
    lines.append(full_text)
    lines.append("")
    lines.append("---")
    lines.append("")

    # 删除决策明细
    if delete_decisions:
        lines.append("## ✂️ 删除决策明细")
        lines.append("")
        lines.append("> ⚠️ 请仔细审核以下删除决策，确认无误后再执行剪辑")
        lines.append("")
        lines.append("### 重复段落删除")
        lines.append("")

        if repeat_deletes:
            for i, d in enumerate(repeat_deletes, 1):
                start_tc = seconds_to_timecode(d["segment_start"])
                end_tc = seconds_to_timecode(d["segment_end"])
                duration = d["segment_end"] - d["segment_start"]
                lines.append(f"#### 重复段 {i}")
                lines.append(f"- **时间轴**: `{start_tc}` → `{end_tc}` （时长: {duration:.1f}s）")
                lines.append(f"- **内容**: 「{d['text']}」")
                if d.get("script_sentence"):
                    lines.append(f"- **对应脚本句**: 「{d['script_sentence']}」")
                lines.append(f"- **删除原因**: {d['reason']}")
                lines.append(f"- **综合评分**: {d.get('score', 'N/A')}")
                lines.append("")
        else:
            lines.append("*无重复段落需要删除*")
            lines.append("")

        lines.append("### 过长静音压缩")
        lines.append("")

        if silence_deletes:
            for i, d in enumerate(silence_deletes, 1):
                start_tc = seconds_to_timecode(d["segment_start"])
                end_tc = seconds_to_timecode(d["segment_end"])
                duration = d["segment_end"] - d["segment_start"]
                lines.append(f"{i}. `{start_tc}` → `{end_tc}` "
                              f"（{duration:.2f}s）— {d['reason']}")
        else:
            lines.append("*无过长静音需要处理*")
        lines.append("")

    # 保留段落总览
    lines.append("---")
    lines.append("")
    lines.append("## ✅ 保留段落总览")
    lines.append("")
    lines.append("| # | 开始 | 结束 | 时长 | 内容 |")
    lines.append("|---|------|------|------|------|")

    for i, d in enumerate(keep_decisions, 1):
        start_tc = seconds_to_timecode(d["segment_start"])
        end_tc = seconds_to_timecode(d["segment_end"])
        duration = d["segment_end"] - d["segment_start"]
        text_preview = d["text"][:30] + "..." if len(d["text"]) > 30 else d["text"]
        lines.append(f"| {i} | {start_tc} | {end_tc} | {duration:.1f}s | {text_preview} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🚀 执行剪辑")
    lines.append("")
    lines.append("确认以上决策无误后，执行剪辑：")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/execute_cut.py --input video.MOV --decisions cut_decisions.json --output video_cut.mp4")
    lines.append("```")
    lines.append("")

    report_content = "\n".join(lines)

    # 保存
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path_obj, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"[OK] 审核报告生成: {output_path}")
    print(f"[INFO] 计划删除 {len(delete_decisions)} 段，保留 {len(keep_decisions)} 段")
    print(f"[INFO] 预计削减时长: {deleted_duration:.1f}s")

    return report_content


def main():
    parser = argparse.ArgumentParser(
        description="生成Markdown格式粗剪审核报告"
    )
    parser.add_argument("--decisions", "-d", required=True, help="cut_decisions.json文件路径")
    parser.add_argument("--transcript", "-t", required=True, help="transcript.json文件路径")
    parser.add_argument("--output", "-o", default="cut_report.md", help="输出Markdown路径")
    parser.add_argument("--video", "-v", default=None, help="原始视频文件名（可选）")
    args = parser.parse_args()

    try:
        generate_review_report(args.decisions, args.transcript, args.output, args.video)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
