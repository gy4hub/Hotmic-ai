#!/usr/bin/env python3
"""
classify_edit.py
对 diff_analyzer.py 输出的修改点进行分类（7类）。
分类逻辑基于启发式规则，可被 LLM 增强。
"""

import json
import re
import sys
from pathlib import Path
from typing import List, Optional

# 7类分类代码
CATEGORIES = ["tone", "structure", "fact", "wording", "length", "platform", "compliance"]

# ─── 分类启发式规则 ────────────────────────────────────────────────────────────

# compliance: 合规调整特征词
COMPLIANCE_SIGNALS = [
    r"确诊|诊断|你这是|你可能是|根据你的情况",
    r"一定能|保证|肯定会|绝对|100%有效|根治|彻底",
    r"（注：来源|来源：http|参考文献）",
    r"某品牌|品牌名",
]

# wording: 措辞替换特征（原文和改文都很短，且是词汇级别的替换）
WORDING_PAIRS = [
    ("但是", "不过"),
    ("然而", "但"),
    ("需要注意的是", "有一点要说"),
    ("研究显示", "有研究认为"),
    ("研究表明", "有数据显示"),
    ("建议", "最好"),
    ("应该", "最好"),
    ("可以", "能"),
]

# tone: 语气调整特征词
TONE_COLLOQUIAL_MARKERS = [
    "说真的", "说白了", "换句话说", "你想想", "说实话", "其实啊",
    "说到底", "说实在的", "不瞒你说", "坦白说",
]

# structure: 结构调整特征（段落级别的变化）
STRUCTURE_SIGNALS = [
    "开头", "结尾", "顺序", "先说", "最后说",
]

# fact: 事实修改特征
FACT_SIGNALS = [
    r"\d+\.?\d*\s*%",  # 百分比
    r"\d+\s*(万|亿|个|人|例|名|次)",  # 数量词
    r"https?://",  # URL（新增来源）
    r"μmol|mg/dl|mmol|IU",  # 医学单位
]

# length: 篇幅调整特征（删减比例）
LENGTH_THRESHOLD_RATIO = 0.3  # 原文or改文缩短/增长超过30%视为length类


def classify_single_edit(original_text: str, revised_text: str) -> str:
    """
    对单个修改点进行分类。

    Returns:
        分类代码（7类之一）
    """
    orig = original_text.strip()
    rev = revised_text.strip()

    orig_len = len(orig)
    rev_len = len(rev)

    # 1. compliance 优先检查（合规问题最高优先级）
    for pattern in COMPLIANCE_SIGNALS:
        if re.search(pattern, orig) and not re.search(pattern, rev):
            return "compliance"

    # 2. fact 检查（数据相关）
    for pattern in FACT_SIGNALS:
        if re.search(pattern, orig) != re.search(pattern, rev):
            return "fact"
        if re.search(pattern, rev) and orig != rev:
            # 有数字变化，且是数字场景
            orig_nums = re.findall(r"\d+\.?\d*", orig)
            rev_nums = re.findall(r"\d+\.?\d*", rev)
            if orig_nums != rev_nums:
                return "fact"

    # 3. length 检查（字数变化超过阈值）
    if orig_len > 20 and rev_len > 0:
        ratio = abs(orig_len - rev_len) / orig_len
        if ratio > LENGTH_THRESHOLD_RATIO:
            # 进一步判断：是删除段落（structure？）还是单纯压缩（length？）
            # 若原文行数>3且改文行数<原文50%，判structure
            orig_lines = orig.count("\n") + 1
            rev_lines = rev.count("\n") + 1
            if orig_lines > 3 and rev_lines < orig_lines * 0.5:
                return "structure"
            return "length"

    # 4. wording 检查（固定词对替换）
    for orig_word, rev_word in WORDING_PAIRS:
        if orig_word in orig and rev_word in rev and orig_word not in rev:
            return "wording"

    # 5. structure 检查（段落结构变化）
    orig_lines = orig.count("\n") + 1
    if orig_lines > 3:
        # 多段落的修改，且不是简单压缩
        for signal in STRUCTURE_SIGNALS:
            if signal in rev:
                return "structure"
        return "structure"

    # 6. platform 检查（含平台特征词）
    platform_indicators = [
        "视频号", "抖音", "评论区", "转给", "帮家人", "前3秒",
        "站队", "关注我", "下期见"
    ]
    for indicator in platform_indicators:
        if (indicator in orig) != (indicator in rev):
            return "platform"

    # 7. tone 检查（语气词变化）
    for marker in TONE_COLLOQUIAL_MARKERS:
        if marker in rev and marker not in orig:
            return "tone"

    # 原文中有口语词但改文删除了（变书面）
    for marker in TONE_COLLOQUIAL_MARKERS:
        if marker in orig and marker not in rev:
            return "tone"

    # 情绪词变化
    sharp_words = ["绝对", "必须", "一定", "根本", "从来", "永远"]
    soft_words = ["可能", "也许", "部分", "有时", "一般"]
    orig_sharp = sum(1 for w in sharp_words if w in orig)
    rev_sharp = sum(1 for w in sharp_words if w in rev)
    orig_soft = sum(1 for w in soft_words if w in orig)
    rev_soft = sum(1 for w in soft_words if w in rev)
    if abs(orig_sharp - rev_sharp) > 0 or abs(orig_soft - rev_soft) > 0:
        return "tone"

    # 默认归为 wording
    return "wording"


def classify_edit_points(edit_points: list) -> list:
    """
    对所有修改点进行分类。

    Args:
        edit_points: diff_analyzer.py 输出的 edit_points 列表

    Returns:
        带 category 字段的 edit_points 列表
    """
    classified = []
    for ep in edit_points:
        category = classify_single_edit(
            ep.get("original_text", ""),
            ep.get("revised_text", ""),
        )
        ep_copy = dict(ep)
        ep_copy["category"] = category
        classified.append(ep_copy)
    return classified


def classify_from_file(diff_json_path: str, output_path: str = None) -> dict:
    """
    从 diff JSON 文件加载，分类所有修改点，回写结果。
    """
    with open(diff_json_path, "r", encoding="utf-8") as f:
        diff_result = json.load(f)

    diff_result["edit_points"] = classify_edit_points(diff_result["edit_points"])

    # 统计各类修改数量
    category_counts = {}
    for ep in diff_result["edit_points"]:
        cat = ep.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1
    diff_result["category_summary"] = category_counts

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(diff_result, f, ensure_ascii=False, indent=2)
        print(f"分类结果已写入: {output_path}")

    return diff_result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="对 diff 修改点进行7类分类")
    parser.add_argument("--input", required=True, help="diff_analyzer 输出的 JSON 路径")
    parser.add_argument("--output", default=None, help="输出 JSON 路径")
    parser.add_argument("--summary", action="store_true", help="只打印分类摘要")

    args = parser.parse_args()

    result = classify_from_file(args.input, args.output)

    print("分类摘要：")
    for cat, count in sorted(result.get("category_summary", {}).items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count} 处")

    if not args.summary and not args.output:
        for ep in result["edit_points"]:
            print(f"\n[{ep.get('category', '?')}] {ep['edit_id']}")
            print(f"  原: {ep['original_text'][:60]}...")
            print(f"  改: {ep['revised_text'][:60]}...")


if __name__ == "__main__":
    main()
