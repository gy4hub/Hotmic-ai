#!/usr/bin/env python3
"""
generate_patches.py — 生成选题权重调整补丁和风格规则建议

基于历史数据分析，输出可直接用于更新 persona.json 的 JSON补丁。

补丁格式:
  {
    "sd_weight_patch": {
      "内容主线名": {"delta": +/-float, "reason": "..."}
    },
    "style_patch": [
      {"rule": "...", "confidence": float, "action": "..."}
    ]
  }

用法:
  python generate_patches.py --data content_data.json --output patches.json
  python generate_patches.py --data content_data.json --output patches.json --min-samples 3
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from analyze_single import compute_metrics, BENCHMARKS


# 触发权重调整的阈值
WEIGHT_TRIGGER = {
    "consecutive_high_views": {"threshold": 100000, "count": 3, "delta": +0.05},
    "consecutive_low_completion": {"threshold": 0.25, "count": 2, "delta": -0.03},
    "high_follower_efficiency": {"threshold": 20, "count": 3, "delta": +0.03},
    "low_follower_efficiency": {"threshold": 5, "count": 3, "delta": -0.05}
}


def group_by_content_line(entries: list[dict]) -> dict[str, list[dict]]:
    """按内容主线分组。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    # 按日期排序，分析连续趋势
    sorted_entries = sorted(entries, key=lambda x: x.get("date") or "")
    for entry in sorted_entries:
        line = entry.get("content_line") or "未分类"
        groups[line].append(entry)
    return dict(groups)


def check_consecutive(values: list[float], condition: str, threshold: float, count: int) -> bool:
    """
    检查是否有连续N个值满足条件。

    Args:
        values: 数值列表（按时间顺序）
        condition: "above" 或 "below"
        threshold: 阈值
        count: 连续次数要求
    """
    consecutive = 0
    for val in values:
        if val is None:
            consecutive = 0
            continue
        if condition == "above" and val >= threshold:
            consecutive += 1
        elif condition == "below" and val < threshold:
            consecutive += 1
        else:
            consecutive = 0
        if consecutive >= count:
            return True
    return False


def generate_weight_patches(groups: dict[str, list[dict]], min_samples: int = 3) -> dict:
    """
    根据各内容主线的表现趋势，生成权重调整补丁。

    Args:
        groups: 按内容主线分组的数据
        min_samples: 最少样本数，低于此不生成补丁

    Returns:
        {content_line: {"delta": float, "reason": str}}
    """
    patches = {}

    for line, entries in groups.items():
        if len(entries) < min_samples:
            print(f"[INFO] 主线 '{line}' 样本数不足{min_samples}条，跳过权重分析")
            continue

        metrics_list = [compute_metrics(e) for e in entries]
        views = [e.get("views") for e in entries]
        completions = [m.get("completion_rate") for m in metrics_list]
        follower_effs = [m.get("follower_efficiency") for m in metrics_list]

        reasons = []
        delta = 0.0

        # 检查播放量趋势
        t = WEIGHT_TRIGGER["consecutive_high_views"]
        if check_consecutive(views, "above", t["threshold"], t["count"]):
            delta += t["delta"]
            reasons.append(f"连续{t['count']}条播放量>{t['threshold']//10000}万")

        # 检查完播率趋势
        t = WEIGHT_TRIGGER["consecutive_low_completion"]
        if check_consecutive(completions, "below", t["threshold"], t["count"]):
            delta += t["delta"]
            reasons.append(f"连续{t['count']}条完播率<{t['threshold']:.0%}")

        # 检查涨粉效率
        t = WEIGHT_TRIGGER["high_follower_efficiency"]
        if check_consecutive(follower_effs, "above", t["threshold"], t["count"]):
            delta += t["delta"]
            reasons.append(f"连续{t['count']}条涨粉效率>{t['threshold']}/万播")

        t = WEIGHT_TRIGGER["low_follower_efficiency"]
        if check_consecutive(follower_effs, "below", t["threshold"], t["count"]):
            delta += t["delta"]
            reasons.append(f"连续{t['count']}条涨粉效率<{t['threshold']}/万播")

        if delta != 0 and reasons:
            patches[line] = {
                "delta": round(delta, 3),
                "reason": "；".join(reasons),
                "sample_count": len(entries)
            }

    return patches


def generate_style_patches(entries: list[dict]) -> list[dict]:
    """
    生成风格规则调整建议。

    分析维度：
    - 视频时长与完播率的关系
    - 标题类型（含数字/疑问句/负面词）与播放量的关系
    - 发布时间与播放量的关系
    """
    style_patches = []

    # 1. 视频时长与完播率
    short_entries = [e for e in entries if (e.get("duration_seconds") or 0) < 180]  # <3分钟
    long_entries = [e for e in entries if (e.get("duration_seconds") or 0) >= 300]  # >=5分钟

    if len(short_entries) >= 2 and len(long_entries) >= 2:
        short_cr = [e.get("completion_rate") for e in short_entries
                    if e.get("completion_rate") is not None]
        long_cr = [e.get("completion_rate") for e in long_entries
                   if e.get("completion_rate") is not None]
        if short_cr and long_cr:
            short_avg = sum(short_cr) / len(short_cr)
            long_avg = sum(long_cr) / len(long_cr)
            if short_avg > long_avg:
                improvement = (short_avg - long_avg) / long_avg
                confidence = min(0.9, 0.5 + len(short_entries) * 0.05)
                style_patches.append({
                    "rule": f"{len(short_entries)}条短视频(<3分钟)完播率比长视频高{improvement:.0%}",
                    "confidence": round(confidence, 2),
                    "action": "建议默认控制视频时长在3分钟以内"
                })

    # 2. 标题含具体数字 vs 不含数字
    number_entries = [e for e in entries if any(c.isdigit() for c in (e.get("title") or ""))]
    no_number_entries = [e for e in entries if not any(c.isdigit() for c in (e.get("title") or ""))]

    if len(number_entries) >= 2 and len(no_number_entries) >= 2:
        num_views = [e.get("views") or 0 for e in number_entries]
        no_num_views = [e.get("views") or 0 for e in no_number_entries]
        avg_num = sum(num_views) / len(num_views)
        avg_no_num = sum(no_num_views) / len(no_num_views)

        if avg_num > avg_no_num and avg_no_num > 0:
            improvement = (avg_num - avg_no_num) / avg_no_num
            confidence = min(0.85, 0.5 + len(number_entries) * 0.05)
            style_patches.append({
                "rule": f"标题含具体数字的{len(number_entries)}条视频均播放量比不含数字的高{improvement:.0%}",
                "confidence": round(confidence, 2),
                "action": "建议在标题中加入具体数字（如315、3种方法、5个误区）"
            })

    # 3. 传播款vs收藏款的涨粉效率对比
    spread = [e for e in entries if e.get("content_type") == "传播款"]
    collect = [e for e in entries if e.get("content_type") == "收藏款"]

    if len(spread) >= 2 and len(collect) >= 2:
        from analyze_single import compute_metrics as cm
        spread_fe = [cm(e).get("follower_efficiency") or 0 for e in spread]
        collect_fe = [cm(e).get("follower_efficiency") or 0 for e in collect]
        avg_spread_fe = sum(spread_fe) / len(spread_fe)
        avg_collect_fe = sum(collect_fe) / len(collect_fe)

        if avg_collect_fe > avg_spread_fe * 1.3:
            style_patches.append({
                "rule": f"收藏款涨粉效率（{avg_collect_fe:.1f}/万播）比传播款（{avg_spread_fe:.1f}/万播）高",
                "confidence": 0.7,
                "action": "建议增加收藏款内容占比，提升账号粉丝质量"
            })
        elif avg_spread_fe > avg_collect_fe * 1.3:
            style_patches.append({
                "rule": f"传播款涨粉效率（{avg_spread_fe:.1f}/万播）比收藏款（{avg_collect_fe:.1f}/万播）高",
                "confidence": 0.65,
                "action": "当前账号传播款拉新效率更高，可适当增加传播款比例"
            })

    return style_patches


def generate_patches(
    data_path: str,
    output_path: str,
    min_samples: int = 3
) -> dict:
    """
    生成权重调整补丁主流程。
    """
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    if not entries:
        raise ValueError("数据文件中没有内容条目")

    print(f"[INFO] 分析 {len(entries)} 条内容，生成权重调整补丁...")

    # 按内容主线分组
    groups = group_by_content_line(entries)

    # 生成权重补丁
    weight_patches = generate_weight_patches(groups, min_samples)

    # 生成风格补丁
    style_patches = generate_style_patches(entries)

    result = {
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": str(data_path),
        "total_entries_analyzed": len(entries),
        "sd_weight_patch": weight_patches,
        "style_patch": style_patches
    }

    # 打印摘要
    if weight_patches:
        print(f"[INFO] 生成 {len(weight_patches)} 条权重调整建议:")
        for line, patch in weight_patches.items():
            delta_str = f"+{patch['delta']}" if patch['delta'] > 0 else str(patch['delta'])
            print(f"  {line}: {delta_str} ({patch['reason']})")
    else:
        print("[INFO] 暂无触发权重调整条件的内容主线")

    if style_patches:
        print(f"[INFO] 生成 {len(style_patches)} 条风格规则建议")
    else:
        print("[INFO] 暂无显著风格规律（建议积累更多数据）")

    # 保存
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path_obj, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] 权重调整补丁: {output_path}")
    return result


def main():
    parser = argparse.ArgumentParser(description="生成选题权重调整补丁和风格规则建议")
    parser.add_argument("--data", "-d", required=True, help="content_data.json文件路径")
    parser.add_argument("--output", "-o", default="patches.json", help="输出JSON文件路径")
    parser.add_argument(
        "--min-samples", type=int, default=3,
        help="每个内容主线触发权重调整所需最少样本数（默认: 3）"
    )
    args = parser.parse_args()

    try:
        generate_patches(args.data, args.output, args.min_samples)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
