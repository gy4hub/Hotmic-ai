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


def _resolve_project_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "shared" / "config.json").exists():
            return candidate
    return start.parent.parent


def load_config(config_path: str = None) -> dict:
    """加载全局配置文件"""
    if config_path is None:
        config_path = _resolve_project_root() / "shared" / "config.json"

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_shared_path(relative_path: str) -> Path:
    return _resolve_project_root() / relative_path


def load_creator_profile(profile_path: str = None, config_path: str = None) -> dict:
    """
    加载统一 persona / casey profile。

    Args:
        profile_path: 显式 profile 路径；为空则从 shared/config.json 的 persona.path 读取
        config_path: shared/config.json 路径
    """
    config = load_config(config_path)
    if profile_path is None:
        profile_path = config.get("persona", {}).get("path")
    if not profile_path:
        return {}

    path = Path(profile_path)
    if not path.is_absolute():
        path = _resolve_shared_path(profile_path)
    if not path.exists():
        print(f"[load_style_rules] 未找到 persona/profile: {path}", file=sys.stderr)
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def format_profile_summary(profile: dict) -> str:
    """将 profile 摘要格式化为可读文本。"""
    if not profile:
        return "暂无可用创作者 profile。"

    positioning = profile.get("positioning") or {}
    decision_layer = (profile.get("dual_audience_model") or {}).get("decision_layer") or {}
    spread_layer = (profile.get("dual_audience_model") or {}).get("spread_layer") or {}
    mix = profile.get("content_mix") or {}

    lines = [
        "## 创作者 Profile 摘要",
        f"- 账号: {profile.get('account_id') or 'unknown'}",
        f"- 名称: {profile.get('display_name') or positioning.get('identity') or '未填写'}",
        f"- 定位: {positioning.get('one_liner') or '未填写'}",
    ]

    if decision_layer:
        lines.append(
            f"- 决策层: {decision_layer.get('label') or '未命名'} | "
            f"{decision_layer.get('who') or '未填写'}"
        )
    if spread_layer:
        lines.append(
            f"- 传播层: {spread_layer.get('label') or '未命名'} | "
            f"{spread_layer.get('who') or '未填写'}"
        )

    line_entries = mix.get("lines") or []
    if isinstance(line_entries, list) and line_entries:
        lines.append("- 内容主线:")
        for entry in line_entries:
            if not isinstance(entry, dict):
                continue
            lines.append(
                f"  - {entry.get('name') or entry.get('key')}: "
                f"{entry.get('weight', 0)}"
            )

    return "\n".join(lines)


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
        db_path = _resolve_shared_path(config["style_db"]["path"])

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
    parser.add_argument("--profile", type=str, default=None, help="统一 persona/profile 路径")
    parser.add_argument("--summary", action="store_true", help="打印规则摘要（调试用）")
    parser.add_argument("--profile-summary", action="store_true", help="打印创作者 profile 摘要")
    parser.add_argument("--output", type=str, default=None, help="输出到文件（不指定则打印到 stdout）")

    args = parser.parse_args()

    rules = load_style_rules(db_path=args.db, threshold=args.threshold)
    profile = load_creator_profile(profile_path=args.profile)

    if args.profile_summary:
        print(format_profile_summary(profile))
        if not args.summary and not args.output:
            return

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
