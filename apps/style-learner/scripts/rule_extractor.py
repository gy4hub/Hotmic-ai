#!/usr/bin/env python3
"""
rule_extractor.py
从分类后的 diff 中提取规则候选。
对每个修改点，根据其分类生成结构化的规则描述。
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import List, Optional


def extract_wording_rule(original_text: str, revised_text: str) -> Optional[str]:
    """
    从 wording 类修改中提取词汇替换规则。
    查找哪个词被替换为哪个词。
    """
    # 预定义词对检测
    KNOWN_PAIRS = [
        ("但是", "不过"),
        ("然而", "但"),
        ("需要注意的是", "有一点要说"),
        ("研究显示", "有研究认为"),
        ("研究表明", "有数据显示"),
        ("应该", "最好"),
        ("建议大家", "建议"),
        ("非常", "很"),
        ("十分", "很"),
        ("总而言之", "说到底"),
        ("综上所述", "所以"),
    ]

    for orig_word, rev_word in KNOWN_PAIRS:
        if orig_word in original_text and rev_word in revised_text and orig_word not in revised_text:
            return f"将'{orig_word}'替换为'{rev_word}'"

    # 通用词对检测：找到被删除的词和新增的词（短词）
    orig_words = set(re.findall(r"[\u4e00-\u9fa5]{2,4}", original_text))
    rev_words = set(re.findall(r"[\u4e00-\u9fa5]{2,4}", revised_text))
    removed = orig_words - rev_words
    added = rev_words - orig_words

    # 若只有少量词变化（1-2个），可能是词汇替换
    if len(removed) == 1 and len(added) == 1:
        orig_w = list(removed)[0]
        rev_w = list(added)[0]
        # 确保这些词在原文/改文中的出现确实是替换关系
        if original_text.count(orig_w) == revised_text.count(rev_w):
            return f"将'{orig_w}'替换为'{rev_w}'"

    return None


def extract_tone_rule(original_text: str, revised_text: str) -> Optional[str]:
    """
    从 tone 类修改中提取语气规则。
    """
    # 口语化标记词
    COLLOQUIAL_MARKERS = [
        "说真的", "说白了", "换句话说", "你想想", "说实话",
        "其实啊", "说到底", "说实在的", "不瞒你说",
    ]

    added_markers = [m for m in COLLOQUIAL_MARKERS if m in revised_text and m not in original_text]
    removed_markers = [m for m in COLLOQUIAL_MARKERS if m in original_text and m not in revised_text]

    if added_markers:
        return f"增加口语化标记词，如'{added_markers[0]}'"

    if removed_markers:
        return f"减少口语化标记词，如'{removed_markers[0]}'"

    # 检测开头反问句 → 陈述句
    if original_text.strip().startswith("你知道") or "？" in original_text[:20]:
        if "？" not in revised_text[:20]:
            return "开头不用反问句，用陈述句+转折制造悬念"

    # 检测软化/强化
    sharp_words = ["绝对", "一定", "必须", "肯定"]
    soft_words = ["可能", "也许", "部分", "有时"]

    orig_sharp = [w for w in sharp_words if w in original_text]
    rev_soft = [w for w in soft_words if w in revised_text]

    if orig_sharp and rev_soft and not any(w in revised_text for w in sharp_words):
        return f"软化确定性表述，将'{orig_sharp[0]}'类词语改为'{rev_soft[0]}'类表达"

    return None


def extract_length_rule(original_text: str, revised_text: str) -> Optional[str]:
    """
    从 length 类修改中提取篇幅规则。
    """
    orig_len = len(original_text.replace("\n", ""))
    rev_len = len(revised_text.replace("\n", ""))

    if orig_len == 0:
        return None

    ratio = (orig_len - rev_len) / orig_len

    if ratio > 0.3:
        # 大幅删减
        if "视频号" in original_text or orig_len > 800:
            return "视频号版控制在1000字以内，删减冗余内容"
        elif "抖音" in original_text:
            return "抖音版比视频号版压缩15-20%，不保留铺垫"
        return "删减重复论证和冗余表述"

    if ratio < -0.3:
        # 大幅扩充
        return "补充具体案例或数据以增加说服力"

    return None


def extract_structure_rule(original_text: str, revised_text: str) -> Optional[str]:
    """
    从 structure 类修改中提取结构规则。
    """
    # 检测开头改为冲击型
    hook_signals = ["花了", "结果", "没想到", "你以为", "但真相是", "错了"]
    if any(s in revised_text[:50] for s in hook_signals) and \
       not any(s in original_text[:50] for s in hook_signals):
        return "开头改为冲突/反转型，增强前3秒钩子效果"

    # 检测结尾变化
    if "评论区" in revised_text[-100:] and "评论区" not in original_text[-100:]:
        return "结尾增加评论区互动引导"

    if "转给" in revised_text[-100:] and "转给" not in original_text[-100:]:
        return "结尾增加转发号召"

    return None


def extract_platform_rule(original_text: str, revised_text: str) -> Optional[str]:
    """
    从 platform 类修改中提取平台适配规则。
    """
    if "视频号" in original_text and "抖音" in revised_text:
        return "视频号和抖音版使用不同的结尾CTA"

    if "评论区告诉我" in revised_text:
        return "抖音版结尾使用'评论区告诉我'引发讨论"

    if "帮家人" in revised_text or "转给" in revised_text:
        return "视频号版结尾侧重'帮家人转一下'"

    return None


EXTRACTORS = {
    "wording": extract_wording_rule,
    "tone": extract_tone_rule,
    "length": extract_length_rule,
    "structure": extract_structure_rule,
    "platform": extract_platform_rule,
    "compliance": lambda o, r: "删除或软化合规风险表述",
    "fact": lambda o, r: None,  # fact 类通常是一次性修正，不提取通用规则
}


def extract_rules_from_diff(classified_diff: dict) -> List[dict]:
    """
    从分类后的 diff 中提取所有规则候选。

    Returns:
        规则候选列表（未去重）
    """
    diff_id = classified_diff.get("diff_id", "unknown")
    rule_candidates = []

    for ep in classified_diff.get("edit_points", []):
        category = ep.get("category", "wording")
        original_text = ep.get("original_text", "")
        revised_text = ep.get("revised_text", "")

        extractor = EXTRACTORS.get(category)
        if extractor is None:
            continue

        rule_text = extractor(original_text, revised_text)
        if rule_text is None:
            continue

        candidate = {
            "category": category,
            "rule": rule_text,
            "source_diff_id": diff_id,
            "source_edit_id": ep.get("edit_id", ""),
        }
        rule_candidates.append(candidate)

    return rule_candidates


def deduplicate_candidates(candidates: List[dict]) -> List[dict]:
    """
    对规则候选去重：相同category+rule的合并，计算出现次数。
    """
    rule_map = defaultdict(lambda: {"count": 0, "source_diffs": set()})

    for c in candidates:
        key = f"{c['category']}::{c['rule']}"
        rule_map[key]["category"] = c["category"]
        rule_map[key]["rule"] = c["rule"]
        rule_map[key]["count"] += 1
        rule_map[key]["source_diffs"].add(c["source_diff_id"])

    deduplicated = []
    for key, data in rule_map.items():
        deduplicated.append({
            "category": data["category"],
            "rule": data["rule"],
            "occurrence_count": data["count"],
            "source_diffs": list(data["source_diffs"]),
        })

    # 按出现次数降序
    deduplicated.sort(key=lambda x: -x["occurrence_count"])
    return deduplicated


def main():
    import argparse

    parser = argparse.ArgumentParser(description="从分类后的 diff 提取规则候选")
    parser.add_argument("--input", required=True, help="classify_edit 输出的 JSON 路径")
    parser.add_argument("--output", default=None, help="输出规则候选 JSON 路径")

    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        classified_diff = json.load(f)

    candidates = extract_rules_from_diff(classified_diff)
    deduplicated = deduplicate_candidates(candidates)

    result = {
        "diff_id": classified_diff.get("diff_id"),
        "rule_candidates": deduplicated,
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"规则候选已写入: {args.output}")
    else:
        print(f"提取到 {len(deduplicated)} 条规则候选：")
        for r in deduplicated:
            print(f"  [{r['category']}] {r['rule']} (出现{r['occurrence_count']}次)")


if __name__ == "__main__":
    main()
