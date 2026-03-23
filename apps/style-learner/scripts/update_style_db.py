#!/usr/bin/env python3
"""
update_style_db.py
自动模式主入口：接收原稿和改稿，运行完整学习流程，更新 style_db.json。

完整流程：
1. 加载原稿 + 改稿
2. 文本 diff → 识别所有修改点（diff_analyzer）
3. 修改点分类（classify_edit）
4. 提取规则候选（rule_extractor）
5. 与 style_db 中已有规则比对、更新 confidence
6. 写入 style_db.json
7. 更新 statistics（edit_ratio_history）
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

# 导入同目录下的模块
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from diff_analyzer import analyze_diff
from classify_edit import classify_edit_points
from rule_extractor import extract_rules_from_diff, deduplicate_candidates


def _resolve_project_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "shared" / "style_db.json").exists():
            return candidate
    return start.parent.parent


# ─── 置信度调整常量 ─────────────────────────────────────────────────────────

INITIAL_CONFIDENCE = 0.3
CONFIDENCE_INCREMENT = 0.2
CONFIDENCE_MAX = 1.0

SIMILARITY_THRESHOLD = 0.8  # 两条规则相似度高于此值视为同一规则


def load_style_db(db_path: str) -> dict:
    """加载 style_db.json，若不存在则创建空库"""
    if Path(db_path).exists():
        with open(db_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": "1.0",
        "last_updated": "",
        "statistics": {
            "total_diffs_analyzed": 0,
            "avg_edit_ratio": 0.0,
            "edit_ratio_history": [],
        },
        "rules": [],
    }


def save_style_db(db: dict, db_path: str) -> None:
    """保存 style_db.json"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def rule_similarity(rule_a: str, rule_b: str) -> float:
    """
    简单计算两条规则描述的相似度。
    基于字符重叠率，足够用于中文规则匹配。
    """
    if rule_a == rule_b:
        return 1.0
    set_a = set(rule_a)
    set_b = set(rule_b)
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def find_matching_rule(candidate: dict, existing_rules: list) -> dict | None:
    """
    在已有规则库中查找与候选规则匹配的规则。
    匹配条件：相同 category 且规则文本相似度 >= SIMILARITY_THRESHOLD
    """
    for rule in existing_rules:
        if rule.get("status") == "deleted":
            continue
        if rule.get("category") != candidate.get("category"):
            continue
        similarity = rule_similarity(rule.get("rule", ""), candidate.get("rule", ""))
        if similarity >= SIMILARITY_THRESHOLD:
            return rule
    return None


def generate_rule_id(existing_rules: list) -> str:
    """生成唯一规则ID"""
    existing_ids = {r.get("id", "") for r in existing_rules}
    counter = len(existing_rules) + 1
    while True:
        rule_id = f"style_{counter:03d}"
        if rule_id not in existing_ids:
            return rule_id
        counter += 1


def update_statistics(db: dict, edit_ratio: float) -> None:
    """更新 statistics 字段"""
    stats = db.setdefault("statistics", {
        "total_diffs_analyzed": 0,
        "avg_edit_ratio": 0.0,
        "edit_ratio_history": [],
    })

    stats["total_diffs_analyzed"] = stats.get("total_diffs_analyzed", 0) + 1

    history = stats.get("edit_ratio_history", [])
    history.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "edit_ratio": round(edit_ratio, 4),
    })
    stats["edit_ratio_history"] = history[-50:]  # 只保留最近50条

    # 更新平均改稿率
    if history:
        stats["avg_edit_ratio"] = round(
            sum(h["edit_ratio"] for h in history) / len(history), 4
        )


def process_candidates(candidates: list, db: dict, diff_id: str) -> dict:
    """
    处理规则候选，更新 style_db 中的规则。

    Returns:
        处理摘要：新增/更新/跳过的数量
    """
    rules = db.setdefault("rules", [])
    today = datetime.now().strftime("%Y-%m-%d")

    summary = {"new": 0, "updated": 0, "skipped": 0}

    for candidate in candidates:
        if not candidate.get("rule"):
            continue

        matching_rule = find_matching_rule(candidate, rules)

        if matching_rule:
            # 已有类似规则 → 提升 confidence
            old_confidence = matching_rule.get("confidence", 0)
            new_confidence = min(old_confidence + CONFIDENCE_INCREMENT, CONFIDENCE_MAX)
            matching_rule["confidence"] = round(new_confidence, 2)
            matching_rule["last_validated"] = today

            # 添加来源 diff
            source_diffs = matching_rule.get("source_diffs", [])
            if diff_id not in source_diffs:
                source_diffs.append(diff_id)
            matching_rule["source_diffs"] = source_diffs

            summary["updated"] += 1
        else:
            # 新规则 → 创建，初始 confidence = 0.3
            new_rule = {
                "id": generate_rule_id(rules),
                "category": candidate["category"],
                "rule": candidate["rule"],
                "confidence": INITIAL_CONFIDENCE,
                "source_diffs": [diff_id],
                "created_at": today,
                "last_validated": today,
                "status": "candidate",
            }
            rules.append(new_rule)
            summary["new"] += 1

    return summary


def run_learning_pipeline(
    original_path: str,
    revised_path: str,
    db_path: str,
    diff_id: str = None,
    verbose: bool = True,
) -> dict:
    """
    完整学习流程：从原稿+改稿到更新 style_db。

    Returns:
        处理摘要
    """
    if diff_id is None:
        diff_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    if verbose:
        print(f"🔍 开始学习流程: {diff_id}")
        print(f"   原稿: {original_path}")
        print(f"   改稿: {revised_path}")

    # Step 1: 文本 diff
    diff_result = analyze_diff(
        original_path=original_path,
        revised_path=revised_path,
        diff_id=diff_id,
    )

    if verbose:
        print(f"📊 改稿率: {diff_result['edit_ratio'] * 100:.1f}%，修改点: {diff_result['total_edits']} 处")

    # Step 2: 分类
    classified_points = classify_edit_points(diff_result["edit_points"])
    diff_result["edit_points"] = classified_points

    # 统计分类
    category_counts = {}
    for ep in classified_points:
        cat = ep.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    if verbose:
        print("📂 修改分类：")
        for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1]):
            print(f"   {cat}: {cnt} 处")

    # Step 3: 提取规则候选
    candidates = extract_rules_from_diff(diff_result)
    dedup_candidates = deduplicate_candidates(candidates)

    if verbose:
        print(f"💡 提取规则候选: {len(dedup_candidates)} 条")

    # Step 4: 更新 style_db
    db = load_style_db(db_path)
    update_statistics(db, diff_result["edit_ratio"])
    summary = process_candidates(dedup_candidates, db, diff_id)
    save_style_db(db, db_path)

    if verbose:
        print(f"✅ style_db 更新完成:")
        print(f"   新增规则: {summary['new']} 条")
        print(f"   更新规则: {summary['updated']} 条（confidence 提升）")
        print(f"   总规则数: {len(db['rules'])} 条")

    summary["edit_ratio"] = diff_result["edit_ratio"]
    summary["total_edits"] = diff_result["total_edits"]
    summary["category_counts"] = category_counts
    summary["diff_id"] = diff_id

    return summary


def main():
    import argparse

    parser = argparse.ArgumentParser(description="自动学习模式：从改稿更新风格库")
    parser.add_argument("--original", required=True, help="原稿路径")
    parser.add_argument("--revised", required=True, help="改稿路径")
    parser.add_argument("--db", default=None, help="style_db.json 路径")
    parser.add_argument("--diff-id", default=None, help="diff ID（不指定则自动生成）")
    parser.add_argument("--quiet", action="store_true", help="静默模式")

    args = parser.parse_args()

    # 默认 db 路径
    db_path = args.db
    if db_path is None:
        project_root = _resolve_project_root()
        db_path = str(project_root / "shared" / "style_db.json")

    summary = run_learning_pipeline(
        original_path=args.original,
        revised_path=args.revised,
        db_path=db_path,
        diff_id=args.diff_id,
        verbose=not args.quiet,
    )

    if not args.quiet:
        print(f"\n学习完成。本次改稿率: {summary['edit_ratio'] * 100:.1f}%")


if __name__ == "__main__":
    main()
