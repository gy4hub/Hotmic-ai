#!/usr/bin/env python3
"""
load_style_rules.py
从 style_db.json 加载高置信度风格规则，格式化为 prompt 补丁注入系统提示。
供 hotmic-script-creator 在每次创作前调用。
"""

import json
import os
import sys
from pathlib import Path


def load_config(config_path: str = None) -> dict:
    """加载全局配置文件"""
    if config_path is None:
        # 默认路径：从当前脚本位置向上找 shared/config.json
        script_dir = Path(__file__).parent
        config_path = script_dir.parent.parent / "shared" / "config.json"

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_style_rules(db_path: str = None, threshold: float = None) -> list:
    """
    从 style_db.json 读取风格规则。

    Args:
        db_path: style_db.json 的路径，为空则从 config.json 读取
        threshold: 置信度阈值，低于此值的规则不加载，为空则从 config.json 读取

    Returns:
        符合条件的规则列表，按 confidence 降序排列
    """
    config = load_config()

    if db_path is None:
        # 相对于项目根目录
        script_dir = Path(__file__).parent
        project_root = script_dir.parent.parent
        db_path = project_root / config["style_db"]["path"]

    if threshold is None:
        threshold = config["style_db"]["confidence_threshold"]

    if not Path(db_path).exists():
        print(f"[load_style_rules] 未找到 style_db.json: {db_path}", file=sys.stderr)
        return []

    with open(db_path, "r", encoding="utf-8") as f:
        db = json.load(f)

    rules = db.get("rules", [])

    # 过滤：confidence >= threshold 且 status != "deleted"
    filtered = [
        r for r in rules
        if r.get("confidence", 0) >= threshold
        and r.get("status", "candidate") != "deleted"
    ]

    # 按 confidence 降序排列
    filtered.sort(key=lambda r: r.get("confidence", 0), reverse=True)

    return filtered


def format_style_patch(rules: list) -> str:
    """
    将规则列表格式化为 prompt 补丁文本。

    Args:
        rules: load_style_rules() 返回的规则列表

    Returns:
        可直接注入系统提示的字符串
    """
    if not rules:
        return ""

    lines = [
        "## 创作者风格偏好（从历史改稿中学习）",
        "以下规则已通过创作者多次确认，创作时请严格遵循：",
    ]

    for rule in rules:
        category = rule.get("category", "general")
        rule_text = rule.get("rule", "")
        confidence = rule.get("confidence", 0)
        status = rule.get("status", "candidate")

        # confirmed 规则用更强的措辞
        if status == "confirmed":
            prefix = "【已确认】"
        else:
            prefix = ""

        lines.append(
            f"- [{category}] {prefix}{rule_text} (confidence: {confidence:.2f})"
        )

    return "\n".join(lines)


def get_style_patch_for_prompt(db_path: str = None, threshold: float = None) -> str:
    """
    一步完成：加载规则 + 格式化为 prompt 补丁。
    这是 script-creator 调用的主要入口。

    Returns:
        prompt 补丁字符串，若无规则则返回空字符串
    """
    rules = load_style_rules(db_path=db_path, threshold=threshold)
    return format_style_patch(rules)


def print_rules_summary(rules: list) -> None:
    """打印规则摘要，供调试使用"""
    if not rules:
        print("暂无符合条件的风格规则。")
        return

    print(f"已加载 {len(rules)} 条风格规则：")
    print("-" * 50)
    for rule in rules:
        status_icon = "✅" if rule.get("status") == "confirmed" else "🔵"
        print(
            f"{status_icon} [{rule.get('category')}] "
            f"{rule.get('rule')} "
            f"(confidence: {rule.get('confidence', 0):.2f})"
        )


def main():
    """命令行入口：输出 prompt 补丁或规则摘要"""
    import argparse

    parser = argparse.ArgumentParser(description="加载风格规则并生成 prompt 补丁")
    parser.add_argument("--db", type=str, default=None, help="style_db.json 路径")
    parser.add_argument("--threshold", type=float, default=None, help="置信度阈值")
    parser.add_argument("--summary", action="store_true", help="打印规则摘要（调试用）")
    parser.add_argument("--output", type=str, default=None, help="输出到文件（不指定则打印到 stdout）")

    args = parser.parse_args()

    rules = load_style_rules(db_path=args.db, threshold=args.threshold)

    if args.summary:
        print_rules_summary(rules)
        return

    patch = format_style_patch(rules)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(patch)
        print(f"prompt 补丁已写入: {args.output}")
    else:
        print(patch)


if __name__ == "__main__":
    main()
