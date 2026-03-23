#!/usr/bin/env python3
"""
detect_repeats.py — Step 4: 重复检测 + 综合评分选优

对alignment.json中标记为重复的组，计算综合分数：
  - 文本准确度（与原稿编辑距离）× 0.6
  - 流利度（停顿少、词间隔均匀）× 0.4
保留得分最高的段，其余标记删除。

用法:
  # 有脚本模式（从alignment.json读取）
  python detect_repeats.py --alignment alignment.json --output cut_decisions.json

  # 无脚本模式（直接从transcript.json检测）
  python detect_repeats.py --transcript transcript.json --no-script --output cut_decisions.json
"""

import argparse
import json
import sys
from pathlib import Path

from align_script import (
    normalized_edit_similarity,
    detect_repeats_no_script,
    align_script_to_transcript,
    split_script_sentences
)


def compute_fluency_score(seg: dict, words: list[dict]) -> float:
    """
    计算segment的流利度分数。

    通过segment内的词级时间戳，统计：
    - 停顿次数（词间隔 > 0.3s）
    - 词间隔的标准差（衡量节奏稳定性）

    流利度 = 1 / (停顿次数 + 词间隔标准差 + 1)

    Args:
        seg: segment字典（含start/end/text）
        words: 所有词级时间戳列表

    Returns:
        流利度分数（0-1之间，越高越流利）
    """
    # 过滤出属于该segment的词
    seg_words = [
        w for w in words
        if w["start"] >= seg["start"] - 0.05 and w["end"] <= seg["end"] + 0.05
    ]

    if len(seg_words) < 2:
        return 0.5  # 词太少，给中等分数

    # 计算词间隔
    gaps = []
    for i in range(1, len(seg_words)):
        gap = seg_words[i]["start"] - seg_words[i-1]["end"]
        gaps.append(max(0, gap))

    # 停顿次数（间隔 > 0.3s）
    pause_count = sum(1 for g in gaps if g > 0.3)

    # 词间隔标准差
    mean_gap = sum(gaps) / len(gaps)
    variance = sum((g - mean_gap) ** 2 for g in gaps) / len(gaps)
    std_gap = variance ** 0.5

    # 流利度分数
    fluency = 1.0 / (pause_count + std_gap + 1.0)
    return min(fluency, 1.0)


def score_segment(
    seg_text: str,
    script_sentence: str,
    seg: dict,
    words: list[dict]
) -> float:
    """
    计算segment的综合评分。

    综合分 = 0.6 × 文本准确度 + 0.4 × 流利度

    Args:
        seg_text: segment转录文本
        script_sentence: 对应的脚本原文
        seg: segment字典（含时间戳）
        words: 词级时间戳

    Returns:
        综合分（0-1）
    """
    text_accuracy = normalized_edit_similarity(seg_text, script_sentence)
    fluency = compute_fluency_score(seg, words)
    return 0.6 * text_accuracy + 0.4 * fluency


def decide_with_script(alignment: dict, words: list[dict]) -> list[dict]:
    """
    有脚本模式：基于alignment结果生成删除决策。

    Args:
        alignment: align_script.py的输出
        words: 词级时间戳

    Returns:
        cut_decisions列表
    """
    decisions = []
    segments = alignment.get("segments", [])

    for sentence_data in alignment.get("alignment", []):
        matched = sentence_data.get("matched_segments", [])
        script_sentence = sentence_data["script_sentence"]
        is_repeated = sentence_data["is_repeated"]

        if not matched:
            continue

        if not is_repeated:
            # 不是重复，直接保留
            seg = matched[0]
            decisions.append({
                "segment_start": seg["start"],
                "segment_end": seg["end"],
                "text": seg["text"],
                "action": "keep",
                "reason": "唯一匹配，直接保留",
                "score": round(seg["similarity"], 4),
                "script_sentence": script_sentence
            })
        else:
            # 重复！对每个匹配段评分，选出最优
            scored = []
            for m in matched:
                # 找到对应的原始segment（含时间戳）
                seg_data = next(
                    (s for s in segments
                     if abs(s["start"] - m["start"]) < 0.01),
                    {"start": m["start"], "end": m["end"], "text": m["text"]}
                )
                score = score_segment(m["text"], script_sentence, seg_data, words)
                scored.append({
                    "segment_start": m["start"],
                    "segment_end": m["end"],
                    "text": m["text"],
                    "score": round(score, 4),
                    "similarity": m["similarity"]
                })

            # 按分数降序排列，最高分保留
            scored.sort(key=lambda x: x["score"], reverse=True)
            best = scored[0]
            others = scored[1:]

            decisions.append({
                "segment_start": best["segment_start"],
                "segment_end": best["segment_end"],
                "text": best["text"],
                "action": "keep",
                "reason": f"重复组最优版本（综合分{best['score']:.3f}）",
                "score": best["score"],
                "script_sentence": script_sentence
            })

            for other in others:
                decisions.append({
                    "segment_start": other["segment_start"],
                    "segment_end": other["segment_end"],
                    "text": other["text"],
                    "action": "delete",
                    "reason": (
                        f"重复段落（与脚本句重复），综合分{other['score']:.3f} < "
                        f"最优版本{best['score']:.3f}"
                    ),
                    "score": other["score"],
                    "script_sentence": script_sentence
                })

    # 处理没有被任何脚本句匹配到的segment（可能是出戏的部分）
    matched_starts = {d["segment_start"] for d in decisions}
    for seg in segments:
        if seg["start"] not in matched_starts:
            decisions.append({
                "segment_start": seg["start"],
                "segment_end": seg["end"],
                "text": seg["text"],
                "action": "keep",
                "reason": "未匹配到脚本句，默认保留",
                "score": 0.0,
                "script_sentence": None
            })

    # 按时间排序
    decisions.sort(key=lambda x: x["segment_start"])
    return decisions


def decide_no_script(alignment: dict, segments: list[dict], words: list[dict]) -> list[dict]:
    """
    无脚本模式：基于相邻相似对生成删除决策。

    对每对相邻的相似segment，保留时长更长的那个。

    Args:
        alignment: align_script.py的无脚本输出
        segments: 所有segment（含时间戳）
        words: 词级时间戳

    Returns:
        cut_decisions列表
    """
    similar_pairs = alignment.get("similar_pairs", [])
    to_delete = set()

    for pair in similar_pairs:
        idx_a = pair["seg_a"]
        idx_b = pair["seg_b"]
        seg_a = segments[idx_a]
        seg_b = segments[idx_b]

        dur_a = seg_a["end"] - seg_a["start"]
        dur_b = seg_b["end"] - seg_b["start"]

        # 保留时长更长的（更完整的表述）
        if dur_a >= dur_b:
            to_delete.add(idx_b)
        else:
            to_delete.add(idx_a)

    decisions = []
    for i, seg in enumerate(segments):
        if i in to_delete:
            pair_info = next(
                (p for p in similar_pairs if p["seg_a"] == i or p["seg_b"] == i),
                {}
            )
            decisions.append({
                "segment_start": seg["start"],
                "segment_end": seg["end"],
                "text": seg["text"],
                "action": "delete",
                "reason": f"相邻重复段（相似度{pair_info.get('similarity', 0):.3f}），保留更长版本",
                "score": 0.0,
                "script_sentence": None
            })
        else:
            decisions.append({
                "segment_start": seg["start"],
                "segment_end": seg["end"],
                "text": seg["text"],
                "action": "keep",
                "reason": "无重复或为重复组中的最优版本",
                "score": 1.0,
                "script_sentence": None
            })

    decisions.sort(key=lambda x: x["segment_start"])
    return decisions


def detect_repeats(
    alignment_path: str | None,
    transcript_path: str | None,
    output_path: str,
    no_script: bool = False
) -> list[dict]:
    """
    主重复检测函数。

    Args:
        alignment_path: 对齐JSON文件路径（有脚本模式）
        transcript_path: 转录JSON文件路径（无脚本模式需要）
        output_path: 输出JSON文件路径
        no_script: 是否使用无脚本模式

    Returns:
        cut_decisions列表
    """
    # 加载转录数据（两种模式都需要words）
    if transcript_path:
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = json.load(f)
        words = transcript.get("words", [])
        segments = transcript.get("segments", [])
    else:
        words = []
        segments = []

    if no_script:
        # 无脚本模式
        if not transcript_path:
            raise ValueError("无脚本模式需要提供 --transcript 参数")

        print(f"[INFO] 无脚本模式：基于 {len(segments)} 个segment检测重复")
        from align_script import detect_repeats_no_script
        similar_pairs = detect_repeats_no_script(segments)

        # 构建对齐数据结构
        alignment_data = {
            "mode": "no_script",
            "segments": segments,
            "similar_pairs": similar_pairs
        }
        decisions = decide_no_script(alignment_data, segments, words)

    else:
        # 有脚本模式
        if not alignment_path:
            raise ValueError("有脚本模式需要提供 --alignment 参数")

        with open(alignment_path, "r", encoding="utf-8") as f:
            alignment_data = json.load(f)

        # 如果没有单独传transcript，尝试从alignment中获取segments
        if not segments:
            segments = alignment_data.get("segments", [])

        print(f"[INFO] 有脚本模式：处理 {len(alignment_data.get('alignment', []))} 个脚本句的对齐结果")
        decisions = decide_with_script(alignment_data, words)

    # 统计
    keep_count = sum(1 for d in decisions if d["action"] == "keep")
    delete_count = sum(1 for d in decisions if d["action"] == "delete")
    print(f"[INFO] 决策结果: 保留 {keep_count} 段, 删除 {delete_count} 段")

    # 保存
    output = {
        "total": len(decisions),
        "keep": keep_count,
        "delete": delete_count,
        "decisions": decisions
    }

    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path_obj, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[OK] 删除决策保存到: {output_path}")
    return decisions


def main():
    parser = argparse.ArgumentParser(
        description="重复段落检测 + 综合评分选优，生成剪辑决策"
    )
    parser.add_argument("--alignment", "-a", default=None, help="对齐JSON文件路径（有脚本模式）")
    parser.add_argument("--transcript", "-t", default=None, help="转录JSON文件路径")
    parser.add_argument("--output", "-o", default="cut_decisions.json", help="输出JSON文件路径")
    parser.add_argument("--no-script", action="store_true", help="无脚本模式（基于n-gram相似度检测重复）")
    args = parser.parse_args()

    if not args.no_script and not args.alignment:
        parser.error("有脚本模式需要 --alignment 参数，或使用 --no-script 切换到无脚本模式")

    try:
        detect_repeats(args.alignment, args.transcript, args.output, args.no_script)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
