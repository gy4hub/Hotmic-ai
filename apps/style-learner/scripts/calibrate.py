#!/usr/bin/env python3
"""
calibrate.py
手动校准模式：展示所有风格规则，允许用户确认/修改/删除。
当用户说"校准风格""看看学到了什么""调整偏好"时触发。
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def _resolve_project_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "shared" / "style_db.json").exists():
            return candidate
    return start.parent.parent


def load_style_db(db_path: str) -> dict:
    """加载 style_db.json"""
    if not Path(db_path).exists():
        print(f"未找到 style_db.json: {db_path}")
        return {"version": "1.0", "rules": [], "statistics": {}}
    with open(db_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_style_db(db: dict, db_path: str) -> None:
    """保存 style_db.json"""
    db["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def display_rules(rules: list) -> None:
    """按 confidence 降序展示所有规则"""
    active_rules = [r for r in rules if r.get("status") != "deleted"]

    if not active_rules:
        print("\n📭 风格库中暂无规则。")
        return

    active_rules.sort(key=lambda r: r.get("confidence", 0), reverse=True)

    print("\n" + "=" * 60)
    print("📚 当前风格规则库")
    print("=" * 60)

    for i, rule in enumerate(active_rules, 1):
        status_icon = "✅" if rule.get("status") == "confirmed" else "🔵"
        confidence = rule.get("confidence", 0)
        confidence_bar = "█" * int(confidence * 10) + "░" * (10 - int(confidence * 10))

        print(f"\n{i}. {status_icon} [{rule.get('category')}] {rule.get('id')}")
        print(f"   规则: {rule.get('rule')}")
        print(f"   置信度: {confidence_bar} {confidence:.2f}")
        print(f"   状态: {rule.get('status')}")
        print(f"   来源: {', '.join(rule.get('source_diffs', []))}")
        print(f"   最后验证: {rule.get('last_validated', '未验证')}")


def display_statistics(db: dict) -> None:
    """展示学习统计数据"""
    stats = db.get("statistics", {})
    history = stats.get("edit_ratio_history", [])

    print("\n" + "=" * 60)
    print("📊 学习统计")
    print("=" * 60)
    print(f"  已分析改稿次数: {stats.get('total_diffs_analyzed', 0)}")
    print(f"  平均改稿率: {stats.get('avg_edit_ratio', 0) * 100:.1f}%")

    if len(history) >= 2:
        recent = history[-5:]
        print(f"\n  最近改稿率趋势（最近{len(recent)}次）:")
        for h in recent:
            bar_width = int(h["edit_ratio"] * 20)
            bar = "▓" * bar_width + "░" * (20 - bar_width)
            print(f"  {h['date']}: {bar} {h['edit_ratio'] * 100:.1f}%")

        first_ratio = history[0]["edit_ratio"]
        last_ratio = history[-1]["edit_ratio"]
        if last_ratio < first_ratio * 0.8:
            print("\n  ✨ 系统正在进化！改稿率持续下降，说明AI越来越懂你了。")
        elif last_ratio > first_ratio * 1.2:
            print("\n  ⚠️ 改稿率有所上升，建议重新校准风格规则。")


def interactive_calibration(db: dict) -> dict:
    """
    交互式校准流程（命令行交互版本）。
    在 Agent 模式下，此函数提供校准逻辑，由 Agent 驱动交互。
    """
    rules = db.get("rules", [])
    active_rules = [r for r in rules if r.get("status") != "deleted"]
    active_rules.sort(key=lambda r: r.get("confidence", 0), reverse=True)

    today = datetime.now().strftime("%Y-%m-%d")
    confirmed_count = 0
    modified_count = 0
    deleted_count = 0

    print("\n开始手动校准。对每条规则，请输入：")
    print("  [Enter] 跳过  |  c: 确认  |  m: 修改  |  d: 删除")
    print("-" * 60)

    for rule in active_rules:
        print(f"\n规则: [{rule.get('category')}] {rule.get('rule')}")
        print(f"置信度: {rule.get('confidence', 0):.2f} | 状态: {rule.get('status')}")

        try:
            action = input("操作 (Enter/c/m/d): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n校准中断。")
            break

        if action == "c":
            rule["confidence"] = 1.0
            rule["status"] = "confirmed"
            rule["last_validated"] = today
            confirmed_count += 1
            print("  ✅ 已确认（confidence = 1.0）")

        elif action == "m":
            try:
                new_text = input(f"  新规则文本（当前：{rule.get('rule')}）: ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if new_text:
                rule["rule"] = new_text
                rule["confidence"] = 0.8
                rule["last_validated"] = today
                modified_count += 1
                print(f"  ✏️ 已修改（confidence = 0.8）")

        elif action == "d":
            rule["status"] = "deleted"
            rule["last_validated"] = today
            deleted_count += 1
            print("  🗑️ 已删除")

    report = {
        "confirmed": confirmed_count,
        "modified": modified_count,
        "deleted": deleted_count,
    }
    return report


def batch_calibration_from_input(db: dict, decisions: list) -> dict:
    """
    批量校准（供 Agent/API 模式调用）。

    Args:
        db: style_db 字典
        decisions: [{"rule_id": "style_001", "action": "confirm/modify/delete", "new_rule": "..."}]

    Returns:
        校准报告
    """
    rules = {r["id"]: r for r in db.get("rules", [])}
    today = datetime.now().strftime("%Y-%m-%d")

    confirmed_count = 0
    modified_count = 0
    deleted_count = 0

    for decision in decisions:
        rule_id = decision.get("rule_id")
        action = decision.get("action", "").lower()

        if rule_id not in rules:
            continue

        rule = rules[rule_id]

        if action == "confirm":
            rule["confidence"] = 1.0
            rule["status"] = "confirmed"
            rule["last_validated"] = today
            confirmed_count += 1

        elif action == "modify":
            new_text = decision.get("new_rule", "")
            if new_text:
                rule["rule"] = new_text
                rule["confidence"] = 0.8
                rule["last_validated"] = today
                modified_count += 1

        elif action == "delete":
            rule["status"] = "deleted"
            rule["last_validated"] = today
            deleted_count += 1

    return {
        "confirmed": confirmed_count,
        "modified": modified_count,
        "deleted": deleted_count,
    }


def print_calibration_report(report: dict, db: dict) -> None:
    """打印校准报告"""
    print("\n" + "=" * 60)
    print("📋 校准报告")
    print("=" * 60)
    print(f"  ✅ 确认: {report.get('confirmed', 0)} 条")
    print(f"  ✏️  修改: {report.get('modified', 0)} 条")
    print(f"  🗑️  删除: {report.get('deleted', 0)} 条")

    active_rules = [r for r in db.get("rules", []) if r.get("status") != "deleted"]
    confirmed_rules = [r for r in active_rules if r.get("status") == "confirmed"]
    print(f"\n  当前有效规则: {len(active_rules)} 条")
    print(f"  已确认规则: {len(confirmed_rules)} 条")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="手动校准风格规则库")
    parser.add_argument("--db", default=None, help="style_db.json 路径")
    parser.add_argument("--show-only", action="store_true", help="只显示规则，不进行校准")
    parser.add_argument("--batch", default=None, help="批量校准决策 JSON 文件路径")

    args = parser.parse_args()

    # 默认 db 路径
    db_path = args.db
    if db_path is None:
        project_root = _resolve_project_root()
        db_path = str(project_root / "shared" / "style_db.json")

    db = load_style_db(db_path)

    display_statistics(db)
    display_rules(db.get("rules", []))

    if args.show_only:
        return

    if args.batch:
        with open(args.batch, "r", encoding="utf-8") as f:
            decisions = json.load(f)
        report = batch_calibration_from_input(db, decisions)
    else:
        report = interactive_calibration(db)

    save_style_db(db, db_path)
    print_calibration_report(report, db)


if __name__ == "__main__":
    main()
