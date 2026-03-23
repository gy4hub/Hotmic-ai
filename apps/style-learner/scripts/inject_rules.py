#!/usr/bin/env python3
"""
inject_rules.py
生成 prompt 补丁供 hotmic-script-creator 调用。
这是 hotmic-style-learner 对外的主要接口。

等同于 hotmic-script-creator/scripts/load_style_rules.py，但以学习模块视角封装，
避免重复代码，统一从此处调用。
"""

import json
import sys
from pathlib import Path


def _resolve_project_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "shared" / "style_db.json").exists():
            return candidate
    return start.parent.parent


def get_style_patch(db_path: str = None, threshold: float = 0.6) -> str:
    """
    从 style_db.json 读取规则并生成 prompt 补丁。
    供 hotmic-script-creator 在创作前调用。

    Args:
        db_path: style_db.json 路径
        threshold: 置信度阈值（默认 0.6）

    Returns:
        prompt 补丁字符串
    """
    if db_path is None:
        project_root = _resolve_project_root()
        db_path = str(project_root / "shared" / "style_db.json")

    if not Path(db_path).exists():
        return ""

    with open(db_path, "r", encoding="utf-8") as f:
        db = json.load(f)

    rules = db.get("rules", [])
    active_rules = [
        r for r in rules
        if r.get("confidence", 0) >= threshold
        and r.get("status") != "deleted"
    ]

    if not active_rules:
        return ""

    active_rules.sort(key=lambda r: r.get("confidence", 0), reverse=True)

    lines = [
        "## 创作者风格偏好（从历史改稿中学习）",
        "以下规则已通过创作者多次确认，创作时请严格遵循：",
    ]

    for rule in active_rules:
        category = rule.get("category", "general")
        rule_text = rule.get("rule", "")
        confidence = rule.get("confidence", 0)
        status = rule.get("status", "candidate")
        prefix = "【已确认】" if status == "confirmed" else ""
        lines.append(f"- [{category}] {prefix}{rule_text} (confidence: {confidence:.2f})")

    return "\n".join(lines)


def get_rules_summary(db_path: str = None) -> dict:
    """
    获取规则库摘要信息，供 Agent 展示使用。

    Returns:
        摘要字典：总规则数、各置信度段分布、最近学习状态
    """
    if db_path is None:
        project_root = _resolve_project_root()
        db_path = str(project_root / "shared" / "style_db.json")

    if not Path(db_path).exists():
        return {"total": 0, "confirmed": 0, "candidate": 0, "avg_edit_ratio": 0}

    with open(db_path, "r", encoding="utf-8") as f:
        db = json.load(f)

    rules = db.get("rules", [])
    active_rules = [r for r in rules if r.get("status") != "deleted"]

    confirmed = [r for r in active_rules if r.get("status") == "confirmed"]
    high_confidence = [r for r in active_rules if r.get("confidence", 0) >= 0.6]
    stats = db.get("statistics", {})

    return {
        "total": len(active_rules),
        "confirmed": len(confirmed),
        "high_confidence": len(high_confidence),
        "avg_edit_ratio": stats.get("avg_edit_ratio", 0),
        "total_diffs_analyzed": stats.get("total_diffs_analyzed", 0),
        "last_updated": db.get("last_updated", "未知"),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="生成风格 prompt 补丁")
    parser.add_argument("--db", default=None, help="style_db.json 路径")
    parser.add_argument("--threshold", type=float, default=0.6, help="置信度阈值")
    parser.add_argument("--summary", action="store_true", help="输出规则库摘要")
    parser.add_argument("--output", default=None, help="输出到文件")

    args = parser.parse_args()

    if args.summary:
        summary = get_rules_summary(args.db)
        print(f"规则库摘要:")
        print(f"  总规则数: {summary['total']}")
        print(f"  已确认: {summary['confirmed']}")
        print(f"  高置信度(>=0.6): {summary['high_confidence']}")
        print(f"  已分析改稿次数: {summary['total_diffs_analyzed']}")
        print(f"  平均改稿率: {summary['avg_edit_ratio'] * 100:.1f}%")
        print(f"  最后更新: {summary['last_updated']}")
        return

    patch = get_style_patch(db_path=args.db, threshold=args.threshold)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(patch)
        print(f"prompt 补丁已写入: {args.output}")
    else:
        print(patch if patch else "（无符合条件的风格规则）")


if __name__ == "__main__":
    main()
