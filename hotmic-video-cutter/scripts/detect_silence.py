#!/usr/bin/env python3
"""
detect_silence.py — Step 5: 过长静音检测

基于Whisper word级时间戳，检测词间隔 > 0.8秒的静音段，
将其标记为"压缩到0.3秒"，追加到cut_decisions.json中。

用法:
  python detect_silence.py --transcript transcript.json --decisions cut_decisions.json
  python detect_silence.py --transcript transcript.json --decisions cut_decisions.json --threshold 1.0
"""

import argparse
import json
import sys
from pathlib import Path


# 默认阈值
SILENCE_THRESHOLD = 0.8   # 超过此时长的静音将被处理（秒）
SILENCE_KEEP = 0.3        # 保留的自然停顿时长（秒）


def detect_silence_segments(
    words: list[dict],
    segments: list[dict],
    threshold: float = SILENCE_THRESHOLD,
    keep_duration: float = SILENCE_KEEP
) -> list[dict]:
    """
    从Whisper词级时间戳中检测过长静音段。

    策略：
    1. 遍历相邻word之间的间隔
    2. 间隔 > threshold → 该段被标记为静音
    3. 生成"保留片段截断"决策：将静音压缩至 keep_duration

    Args:
        words: 词时间戳列表（{word, start, end}）
        segments: 转录segment列表（{start, end, text}）
        threshold: 静音判定阈值（秒）
        keep_duration: 保留的停顿时长（秒）

    Returns:
        静音段决策列表
    """
    if not words:
        # 无词级时间戳时，退回用segment间隔
        return _detect_silence_from_segments(segments, threshold, keep_duration)

    silence_decisions = []

    for i in range(1, len(words)):
        gap = words[i]["start"] - words[i-1]["end"]

        if gap > threshold:
            # 检测到过长静音
            silence_start = words[i-1]["end"]
            silence_end = words[i]["start"]
            excess = gap - keep_duration  # 超出保留时长的部分

            silence_decisions.append({
                "segment_start": silence_start + keep_duration,  # 从保留时长之后开始删除
                "segment_end": silence_end,
                "text": f"[静音 {gap:.2f}s]",
                "action": "delete",
                "reason": f"过长静音（{gap:.2f}s > {threshold}s），保留{keep_duration}s自然停顿，删除{excess:.2f}s",
                "score": 0.0,
                "script_sentence": None,
                "type": "silence"
            })

    return silence_decisions


def _detect_silence_from_segments(
    segments: list[dict],
    threshold: float,
    keep_duration: float
) -> list[dict]:
    """
    退化方案：当无词级时间戳时，基于segment间隔检测静音。
    """
    decisions = []
    for i in range(1, len(segments)):
        gap = segments[i]["start"] - segments[i-1]["end"]
        if gap > threshold:
            excess = gap - keep_duration
            decisions.append({
                "segment_start": segments[i-1]["end"] + keep_duration,
                "segment_end": segments[i]["start"],
                "text": f"[段间静音 {gap:.2f}s]",
                "action": "delete",
                "reason": f"段间过长静音（{gap:.2f}s），保留{keep_duration}s",
                "score": 0.0,
                "script_sentence": None,
                "type": "silence"
            })
    return decisions


def detect_and_merge(
    transcript_path: str,
    decisions_path: str,
    threshold: float = SILENCE_THRESHOLD,
    keep_duration: float = SILENCE_KEEP
) -> dict:
    """
    检测静音并合并到已有的cut_decisions.json中。

    Args:
        transcript_path: 转录JSON文件路径
        decisions_path: cut_decisions.json文件路径（已有重复检测结果）
        threshold: 静音阈值（秒）
        keep_duration: 保留停顿时长（秒）

    Returns:
        更新后的决策字典
    """
    # 加载转录
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    words = transcript.get("words", [])
    segments = transcript.get("segments", [])

    print(f"[INFO] 使用词级时间戳: {'是' if words else '否（退回segment级别）'}")

    # 检测静音
    silence_decisions = detect_silence_segments(words, segments, threshold, keep_duration)
    print(f"[INFO] 检测到 {len(silence_decisions)} 个过长静音段")

    # 加载并合并已有决策
    decisions_path_obj = Path(decisions_path)
    if decisions_path_obj.exists():
        with open(decisions_path_obj, "r", encoding="utf-8") as f:
            existing = json.load(f)
        all_decisions = existing.get("decisions", [])
    else:
        all_decisions = []

    # 追加静音决策
    all_decisions.extend(silence_decisions)

    # 按时间排序
    all_decisions.sort(key=lambda x: x["segment_start"])

    # 更新统计
    keep_count = sum(1 for d in all_decisions if d["action"] == "keep")
    delete_count = sum(1 for d in all_decisions if d["action"] == "delete")
    silence_count = sum(1 for d in all_decisions if d.get("type") == "silence")

    output = {
        "total": len(all_decisions),
        "keep": keep_count,
        "delete": delete_count,
        "silence_segments": silence_count,
        "decisions": all_decisions
    }

    # 回写
    with open(decisions_path_obj, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[OK] 更新到: {decisions_path}")
    print(f"[INFO] 汇总: 保留{keep_count}段, 删除{delete_count}段（含{silence_count}个静音段）")

    return output


def main():
    parser = argparse.ArgumentParser(
        description="检测并标记过长静音段（压缩为0.3s自然停顿）"
    )
    parser.add_argument("--transcript", "-t", required=True, help="转录JSON文件路径")
    parser.add_argument("--decisions", "-d", required=True, help="cut_decisions.json路径（将被追加更新）")
    parser.add_argument(
        "--threshold", type=float, default=SILENCE_THRESHOLD,
        help=f"静音判定阈值（默认: {SILENCE_THRESHOLD}秒）"
    )
    parser.add_argument(
        "--keep", type=float, default=SILENCE_KEEP,
        help=f"保留的停顿时长（默认: {SILENCE_KEEP}秒）"
    )
    args = parser.parse_args()

    try:
        detect_and_merge(args.transcript, args.decisions, args.threshold, args.keep)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
