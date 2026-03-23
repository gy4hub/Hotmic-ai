#!/usr/bin/env python3
"""
align_script.py — Step 3: 脚本-转录对齐（核心算法）

将定稿脚本的每个句子，与Whisper转录的segment做对齐匹配。
一个脚本句匹配到N个转录段（N>1）= 检测到重复录制。

用法:
  python align_script.py --transcript transcript.json --script script.md --output alignment.json
  python align_script.py --transcript transcript.json  # 无脚本模式
"""

import argparse
import json
import re
import sys
from pathlib import Path


def levenshtein_distance(s1: str, s2: str) -> int:
    """计算两个字符串的Levenshtein编辑距离。"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            # 插入、删除、替换
            curr_row.append(min(
                prev_row[j + 1] + 1,   # 删除
                curr_row[j] + 1,       # 插入
                prev_row[j] + (c1 != c2)  # 替换
            ))
        prev_row = curr_row

    return prev_row[-1]


def normalized_edit_similarity(s1: str, s2: str) -> float:
    """
    计算归一化编辑相似度（0-1，1为完全相同）。
    """
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    dist = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    return 1.0 - dist / max_len


def split_script_sentences(script_text: str) -> list[str]:
    """
    将脚本文本按句子分割。
    分隔符：句号、问号、感叹号、换行符（中英文均支持）
    过滤空行和Markdown标题行。
    """
    # 移除Markdown格式但保留换行结构
    lines = script_text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        # 跳过Markdown标题、分割线
        if line.startswith('#') or line.startswith('---'):
            continue
        # 移除Markdown格式
        line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)  # 粗体
        line = re.sub(r'\*(.+?)\*', r'\1', line)       # 斜体
        line = re.sub(r'`(.+?)`', r'\1', line)         # 代码
        cleaned_lines.append(line)  # 保留空行（作为句子分隔符）

    # 用换行符合并（保留换行结构），再按句子标点拆分
    full_text = '\n'.join(cleaned_lines)

    # 按句子分隔符拆分（句号/问号/感叹号/换行符）
    sentences = re.split(r'[。！？\n]+', full_text)
    # 过滤空白句子，保留至少2个字符的有效内容
    sentences = [s.strip() for s in sentences if len(s.strip()) >= 2]

    return sentences


def align_script_to_transcript(
    script_sentences: list[str],
    segments: list[dict],
    similarity_threshold: float = 0.4,
    threshold: float | None = None  # 兼容旧调用方式
) -> list[dict]:
    """
    将脚本句子映射到转录segment。

    策略：对每个脚本句，找到相似度最高的转录段（贪心搜索）。
    相似度 < threshold 的匹配被忽略。

    Args:
        script_sentences: 脚本句子列表
        segments: Whisper转录的segment列表
        similarity_threshold: 最低相似度阈值

    Returns:
        对齐结果列表，每项包含脚本句及其匹配的segment列表
    """
    # 兼容旧调用方式（threshold参数）
    if threshold is not None:
        similarity_threshold = threshold

    alignment = []
    # 记录每个segment已被匹配的次数（允许多次匹配以检测重复）
    seg_match_map: dict[int, list[str]] = {i: [] for i in range(len(segments))}

    for sent_idx, sentence in enumerate(script_sentences):
        matched_segs = []

        for seg_idx, seg in enumerate(segments):
            sim = normalized_edit_similarity(sentence, seg["text"])
            if sim >= similarity_threshold:
                matched_segs.append({
                    "seg_idx": seg_idx,
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                    "similarity": round(sim, 4)
                })
                seg_match_map[seg_idx].append(sentence)

        # 按相似度降序排列
        matched_segs.sort(key=lambda x: x["similarity"], reverse=True)

        alignment.append({
            "sentence_idx": sent_idx,
            "script_sentence": sentence,
            "matched_segments": matched_segs,
            "is_repeated": len(matched_segs) > 1  # 一句话出现多次 = 重复
        })

    return alignment


def detect_repeats_no_script(segments: list[dict], threshold: float = 0.85) -> list[dict]:
    """
    无脚本模式：通过相邻segment之间的相似度检测重复。

    使用字符级n-gram余弦相似度。两个相邻segment相似度 > threshold = 重复。

    Args:
        segments: 转录segment列表
        threshold: 相似度阈值

    Returns:
        相似对列表（相邻重复）
    """
    def char_ngram_similarity(s1: str, s2: str, n: int = 2) -> float:
        """字符级n-gram余弦相似度。"""
        if not s1 or not s2:
            return 0.0

        def get_ngrams(s: str, n: int) -> dict:
            ngrams: dict[str, int] = {}
            for i in range(len(s) - n + 1):
                gram = s[i:i+n]
                ngrams[gram] = ngrams.get(gram, 0) + 1
            return ngrams

        ng1 = get_ngrams(s1, n)
        ng2 = get_ngrams(s2, n)

        # 余弦相似度
        all_grams = set(ng1.keys()) | set(ng2.keys())
        dot = sum(ng1.get(g, 0) * ng2.get(g, 0) for g in all_grams)
        norm1 = sum(v**2 for v in ng1.values()) ** 0.5
        norm2 = sum(v**2 for v in ng2.values()) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    similar_pairs = []
    for i in range(len(segments) - 1):
        sim = char_ngram_similarity(segments[i]["text"], segments[i+1]["text"])
        if sim > threshold:
            similar_pairs.append({
                "seg_a": i,
                "seg_b": i + 1,
                "similarity": round(sim, 4),
                "text_a": segments[i]["text"],
                "text_b": segments[i+1]["text"]
            })

    return similar_pairs


def align(
    transcript_path: str,
    script_path: str | None,
    output_path: str,
    similarity_threshold: float = 0.4
) -> dict:
    """
    主对齐函数：加载转录结果和脚本，执行对齐，保存结果。

    Args:
        transcript_path: 转录JSON文件路径
        script_path: 脚本文件路径（None表示无脚本模式）
        output_path: 输出JSON文件路径
        similarity_threshold: 最低相似度阈值

    Returns:
        对齐结果字典
    """
    # 加载转录
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    segments = transcript.get("segments", [])
    if not segments:
        raise ValueError("转录文件中没有segment数据，请检查转录步骤。")

    result = {
        "mode": "with_script" if script_path else "no_script",
        "total_segments": len(segments),
        "segments": segments
    }

    if script_path:
        # 有脚本模式
        with open(script_path, "r", encoding="utf-8") as f:
            script_text = f.read()

        sentences = split_script_sentences(script_text)
        print(f"[INFO] 脚本共 {len(sentences)} 句，转录共 {len(segments)} 段")

        alignment = align_script_to_transcript(sentences, segments, similarity_threshold)

        repeated_count = sum(1 for a in alignment if a["is_repeated"])
        print(f"[INFO] 检测到 {repeated_count} 个脚本句有重复录制")

        result["script_sentences"] = len(sentences)
        result["alignment"] = alignment
        result["repeated_sentences"] = repeated_count

    else:
        # 无脚本模式
        print(f"[INFO] 无脚本模式：对 {len(segments)} 个segment进行相邻相似度检测")
        similar_pairs = detect_repeats_no_script(segments)
        print(f"[INFO] 检测到 {len(similar_pairs)} 对相似segment")

        result["similar_pairs"] = similar_pairs
        result["repeated_pairs"] = len(similar_pairs)

    # 保存
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] 对齐结果保存到: {output_path}")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="脚本-转录对齐（检测重复录制段落）"
    )
    parser.add_argument("--transcript", "-t", required=True, help="转录JSON文件路径")
    parser.add_argument("--script", "-s", default=None, help="定稿脚本文件路径（.md或.txt）")
    parser.add_argument("--output", "-o", default="alignment.json", help="输出JSON文件路径")
    parser.add_argument(
        "--threshold", "-th", type=float, default=0.4,
        help="最低相似度阈值（默认: 0.4）"
    )
    args = parser.parse_args()

    try:
        align(args.transcript, args.script, args.output, args.threshold)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
