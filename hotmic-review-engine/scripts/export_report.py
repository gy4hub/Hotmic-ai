#!/usr/bin/env python3
"""
export_report.py — 导出完整Markdown复盘报告（汇总版）

整合所有分析结果，生成一份完整的复盘报告文档。

用法:
  python export_report.py --data content_data.json --output full_report.md
  python export_report.py --data content_data.json --patches patches.json --output full_report.md
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 导入其他分析模块
sys.path.insert(0, str(Path(__file__).parent))
from analyze_single import compute_metrics, grade_metric, BENCHMARKS
from analyze_period import (
    analyze_content_lines, analyze_content_types,
    find_best_publish_times, analyze_follower_trend
)


def export_full_report(
    data_path: str,
    output_path: str,
    patches_path: str | None = None
) -> str:
    """
    生成完整汇总复盘报告。

    Args:
        data_path: content_data.json路径
        output_path: 输出Markdown路径
        patches_path: patches.json路径（可选）

    Returns:
        Markdown报告字符串
    """
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    platform = data.get("platform", "未知")

    if not entries:
        raise ValueError("数据文件中没有内容条目")

    # 加载补丁（可选）
    patches = None
    if patches_path and Path(patches_path).exists():
        with open(patches_path, "r", encoding="utf-8") as f:
            patches = json.load(f)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 分析
    line_analysis = analyze_content_lines(entries)
    type_analysis = analyze_content_types(entries)
    best_times = find_best_publish_times(entries)
    follower_trend = analyze_follower_trend(entries)

    # 按播放量排序的top内容
    top_entries = sorted(entries, key=lambda x: x.get("views") or 0, reverse=True)[:5]

    # 整体数据
    total_views = sum(e.get("views") or 0 for e in entries)
    total_followers = sum(e.get("followers_gained") or 0 for e in entries)

    lines = []
    lines.append(f"# {platform} 内容复盘完整报告")
    lines.append("")
    lines.append(f"> 生成时间：{now} | 数据条数：{len(entries)} 条")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 目录
    lines.append("## 目录")
    lines.append("")
    lines.append("1. [整体数据摘要](#整体数据摘要)")
    lines.append("2. [TOP 5 内容](#top-5-内容)")
    lines.append("3. [内容主线对比](#内容主线对比)")
    lines.append("4. [内容类型ROI](#内容类型roi)")
    lines.append("5. [最佳发布时间](#最佳发布时间)")
    lines.append("6. [涨粉效率趋势](#涨粉效率趋势)")
    if patches:
        lines.append("7. [权重调整建议](#权重调整建议)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. 整体摘要
    lines.append("## 整体数据摘要")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 发布条数 | {len(entries)} |")
    lines.append(f"| 总播放量 | {total_views:,} |")
    lines.append(f"| 总新增粉丝 | {total_followers:,} |")
    if total_views:
        lines.append(f"| 平均播放量 | {total_views // len(entries):,} |")
        lines.append(f"| 平均涨粉效率 | {total_followers / total_views * 10000:.1f}/万播 |")
    lines.append("")

    # 2. TOP 5
    lines.append("## TOP 5 内容")
    lines.append("")
    lines.append("| 排名 | 标题 | 日期 | 播放量 | 完播率 | 涨粉 |")
    lines.append("|------|------|------|--------|--------|------|")
    for i, entry in enumerate(top_entries, 1):
        cr = f"{entry.get('completion_rate', 0):.1%}" if entry.get("completion_rate") else "N/A"
        lines.append(
            f"| {i} | {entry.get('title', '')[:25]} | {entry.get('date', '')} | "
            f"{(entry.get('views') or 0):,} | {cr} | {(entry.get('followers_gained') or 0):,} |"
        )
    lines.append("")

    # 3. 内容主线对比
    lines.append("## 内容主线对比")
    lines.append("")
    lines.append("| 主线 | 条数 | 总播放 | 均播放 | 均互动率 | 均完播率 |")
    lines.append("|------|------|--------|--------|----------|----------|")
    for line_name, stats in line_analysis.items():
        cr = f"{stats.get('avg_completion_rate', 0):.1%}" if stats.get("avg_completion_rate") else "N/A"
        lines.append(
            f"| {line_name} | {stats['count']} | {stats['total_views']:,} | "
            f"{stats['avg_views']:,} | {stats.get('avg_engagement_rate', 0):.2%} | {cr} |"
        )
    lines.append("")

    # 4. 内容类型ROI
    lines.append("## 内容类型ROI")
    lines.append("")
    lines.append("| 类型 | 条数 | 均播放 | 均互动率 | 均涨粉效率 | 总涨粉 |")
    lines.append("|------|------|--------|----------|------------|--------|")
    for ctype, stats in type_analysis.items():
        fe = f"{stats.get('avg_follower_efficiency', 0):.1f}/万播" if stats.get("avg_follower_efficiency") else "N/A"
        lines.append(
            f"| {ctype} | {stats['count']} | {stats['avg_views']:,} | "
            f"{stats.get('avg_engagement_rate', 0):.2%} | {fe} | {stats['total_followers']:,} |"
        )
    lines.append("")

    # 5. 最佳发布时间
    if best_times:
        lines.append("## 最佳发布时间")
        lines.append("")
        lines.append("| 时段 | 内容数 | 平均播放量 |")
        lines.append("|------|--------|------------|")
        for slot in best_times:
            lines.append(f"| {slot['time_slot']} | {slot['count']} | {slot['avg_views']:,} |")
        lines.append("")

    # 6. 涨粉趋势
    lines.append("## 涨粉效率趋势")
    lines.append("")
    lines.append("| 日期 | 标题 | 播放量 | 涨粉效率 |")
    lines.append("|------|------|--------|----------|")
    for t in follower_trend:
        lines.append(f"| {t['date']} | {t['title']} | {t['views']:,} | {t['follower_efficiency']:.1f}/万播 |")
    lines.append("")

    # 7. 权重建议（如有）
    if patches:
        lines.append("## 权重调整建议")
        lines.append("")
        weight_patches = patches.get("sd_weight_patch", {})
        style_patches = patches.get("style_patch", [])

        if weight_patches:
            lines.append("### 选题权重调整")
            lines.append("")
            lines.append("| 内容主线 | 调整幅度 | 原因 |")
            lines.append("|----------|----------|------|")
            for line_name, patch in weight_patches.items():
                delta_str = f"+{patch['delta']}" if patch["delta"] > 0 else str(patch["delta"])
                lines.append(f"| {line_name} | {delta_str} | {patch['reason']} |")
            lines.append("")

        if style_patches:
            lines.append("### 创作风格建议")
            lines.append("")
            for patch in style_patches:
                lines.append(f"- **规律**: {patch['rule']}")
                lines.append(f"  - 置信度: {patch['confidence']:.0%}")
                lines.append(f"  - **建议**: {patch['action']}")
                lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*本报告由 HotMic AI（开麦）review-engine 自动生成*")

    report = "\n".join(lines)

    # 保存
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path_obj, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[OK] 完整复盘报告: {output_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="导出完整复盘报告")
    parser.add_argument("--data", "-d", required=True, help="content_data.json文件路径")
    parser.add_argument("--patches", "-p", default=None, help="patches.json文件路径（可选）")
    parser.add_argument("--output", "-o", default="full_report.md", help="输出Markdown文件路径")
    args = parser.parse_args()

    try:
        export_full_report(args.data, args.output, args.patches)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
