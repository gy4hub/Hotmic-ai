#!/usr/bin/env python3
"""
analyze_period.py — 周报/月报分析

对指定时间段内的内容数据，生成：
- 三条内容主线各自表现对比
- 传播款 vs 收藏款 ROI
- 最佳发布时间段
- 涨粉效率趋势

用法:
  python analyze_period.py --data content_data.json --period week --output weekly.md
  python analyze_period.py --data content_data.json --period month --output monthly.md
  python analyze_period.py --data content_data.json --start 2026-03-01 --end 2026-03-31 --output march.md
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def filter_by_period(entries: list[dict], period: str | None, start: str | None, end: str | None) -> list[dict]:
    """
    按时间范围过滤内容条目。

    Args:
        entries: 所有内容条目
        period: 预设时间范围（week/month/quarter）
        start: 开始日期 YYYY-MM-DD
        end: 结束日期 YYYY-MM-DD
    """
    today = datetime.now().date()

    if period == "week":
        start_date = today - timedelta(days=7)
        end_date = today
    elif period == "month":
        start_date = today.replace(day=1)
        end_date = today
    elif period == "quarter":
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        start_date = today.replace(month=quarter_month, day=1)
        end_date = today
    elif start and end:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    else:
        # 无过滤，返回全部
        return entries

    filtered = []
    for entry in entries:
        date_str = entry.get("date")
        if not date_str:
            continue
        try:
            entry_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
            if start_date <= entry_date <= end_date:
                filtered.append(entry)
        except ValueError:
            continue

    return filtered


def compute_entry_metrics(entry: dict) -> dict:
    """计算单条内容的指标。"""
    views = entry.get("views") or 0
    likes = entry.get("likes") or 0
    comments = entry.get("comments") or 0
    shares = entry.get("shares") or 0
    followers = entry.get("followers_gained") or 0

    return {
        "views": views,
        "engagement_rate": round((likes + comments + shares) / views, 4) if views else 0,
        "share_rate": round(shares / views, 4) if views else 0,
        "follower_efficiency": round(followers / views * 10000, 2) if views else 0,
        "completion_rate": entry.get("completion_rate"),
        "followers_gained": followers
    }


def analyze_content_lines(entries: list[dict]) -> dict:
    """
    对三条内容主线分别汇总分析。

    Returns:
        {content_line: {avg_views, avg_engagement, avg_completion, ...}}
    """
    line_groups: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        line = entry.get("content_line") or "未分类"
        line_groups[line].append(entry)

    results = {}
    for line, group in line_groups.items():
        metrics_list = [compute_entry_metrics(e) for e in group]
        count = len(metrics_list)

        def avg(key):
            vals = [m[key] for m in metrics_list if m.get(key) is not None]
            return round(sum(vals) / len(vals), 4) if vals else None

        results[line] = {
            "count": count,
            "total_views": sum(m["views"] for m in metrics_list),
            "total_followers": sum(m["followers_gained"] for m in metrics_list),
            "avg_views": round(sum(m["views"] for m in metrics_list) / count),
            "avg_engagement_rate": avg("engagement_rate"),
            "avg_completion_rate": avg("completion_rate"),
            "avg_share_rate": avg("share_rate"),
            "avg_follower_efficiency": avg("follower_efficiency")
        }

    return dict(sorted(results.items(), key=lambda x: x[1]["total_views"], reverse=True))


def analyze_content_types(entries: list[dict]) -> dict:
    """
    传播款 vs 收藏款的ROI对比。
    """
    type_groups: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        ctype = entry.get("content_type") or "未分类"
        type_groups[ctype].append(entry)

    results = {}
    for ctype, group in type_groups.items():
        metrics_list = [compute_entry_metrics(e) for e in group]
        count = len(metrics_list)

        def avg(key):
            vals = [m[key] for m in metrics_list if m.get(key) is not None]
            return round(sum(vals) / len(vals), 4) if vals else None

        results[ctype] = {
            "count": count,
            "avg_views": round(sum(m["views"] for m in metrics_list) / count) if count else 0,
            "avg_engagement_rate": avg("engagement_rate"),
            "avg_completion_rate": avg("completion_rate"),
            "avg_share_rate": avg("share_rate"),
            "avg_follower_efficiency": avg("follower_efficiency"),
            "total_followers": sum(m["followers_gained"] for m in metrics_list)
        }

    return results


def find_best_publish_times(entries: list[dict]) -> list[dict]:
    """
    分析最佳发布时间段。

    将24小时分为6个时段，计算每个时段的平均播放量。
    """
    time_slots = {
        "06:00-09:00": [],
        "09:00-12:00": [],
        "12:00-14:00": [],
        "14:00-18:00": [],
        "18:00-22:00": [],
        "22:00+": []
    }

    for entry in entries:
        publish_time = entry.get("publish_time")
        views = entry.get("views") or 0
        if not publish_time:
            continue
        try:
            hour = int(str(publish_time).split(":")[0])
        except (ValueError, IndexError):
            continue

        if 6 <= hour < 9:
            time_slots["06:00-09:00"].append(views)
        elif 9 <= hour < 12:
            time_slots["09:00-12:00"].append(views)
        elif 12 <= hour < 14:
            time_slots["12:00-14:00"].append(views)
        elif 14 <= hour < 18:
            time_slots["14:00-18:00"].append(views)
        elif 18 <= hour < 22:
            time_slots["18:00-22:00"].append(views)
        else:
            time_slots["22:00+"].append(views)

    slot_stats = []
    for slot, views_list in time_slots.items():
        if views_list:
            slot_stats.append({
                "time_slot": slot,
                "count": len(views_list),
                "avg_views": round(sum(views_list) / len(views_list))
            })

    return sorted(slot_stats, key=lambda x: x["avg_views"], reverse=True)


def analyze_follower_trend(entries: list[dict]) -> list[dict]:
    """
    按日期排序，分析涨粉效率趋势。
    """
    sorted_entries = sorted(
        entries,
        key=lambda x: x.get("date") or "0000-00-00"
    )

    trend = []
    for entry in sorted_entries:
        metrics = compute_entry_metrics(entry)
        trend.append({
            "date": entry.get("date"),
            "title": entry.get("title", "未命名")[:20],
            "views": metrics["views"],
            "followers_gained": metrics["followers_gained"],
            "follower_efficiency": metrics["follower_efficiency"]
        })

    return trend


def analyze_period(
    data_path: str,
    period: str | None,
    start: str | None,
    end: str | None,
    output_path: str
) -> str:
    """
    周报/月报分析主流程。
    """
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_entries = data.get("entries", [])
    platform = data.get("platform", "未知")

    # 过滤时间范围
    entries = filter_by_period(all_entries, period, start, end)
    if not entries:
        raise ValueError(f"在指定时间范围内没有内容数据（共{len(all_entries)}条）")

    print(f"[INFO] 分析 {len(entries)} 条内容（共 {len(all_entries)} 条）")

    # 各维度分析
    line_analysis = analyze_content_lines(entries)
    type_analysis = analyze_content_types(entries)
    best_times = find_best_publish_times(entries)
    follower_trend = analyze_follower_trend(entries)

    # 整体汇总
    total_views = sum(e.get("views") or 0 for e in entries)
    total_followers = sum(e.get("followers_gained") or 0 for e in entries)

    # 生成报告
    period_label = period or f"{start or '?'} 至 {end or '?'}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append(f"# {platform} 数据复盘报告（{period_label}）")
    lines.append("")
    lines.append(f"**生成时间**: {now} | **分析内容数**: {len(entries)} 条")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 整体摘要
    lines.append("## 📊 整体摘要")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 发布条数 | {len(entries)} 条 |")
    lines.append(f"| 总播放量 | {total_views:,} |")
    lines.append(f"| 总新增粉丝 | {total_followers:,} |")
    lines.append(f"| 平均播放量 | {total_views // len(entries):,} |")
    lines.append(f"| 平均涨粉效率 | {total_followers / total_views * 10000:.1f}/万播" if total_views else f"| 平均涨粉效率 | N/A |")
    lines.append("")

    # 内容主线对比
    lines.append("## 📌 内容主线分析")
    lines.append("")
    lines.append("| 主线 | 条数 | 总播放 | 均播放 | 均互动率 | 均完播率 | 涨粉效率 |")
    lines.append("|------|------|--------|--------|----------|----------|----------|")
    for line_name, stats in line_analysis.items():
        cr = f"{stats.get('avg_completion_rate', 0):.1%}" if stats.get('avg_completion_rate') else "N/A"
        fe = f"{stats.get('avg_follower_efficiency', 0):.1f}/万播" if stats.get('avg_follower_efficiency') else "N/A"
        lines.append(
            f"| {line_name} | {stats['count']} | {stats['total_views']:,} | "
            f"{stats['avg_views']:,} | {stats.get('avg_engagement_rate', 0):.2%} | {cr} | {fe} |"
        )
    lines.append("")

    # 传播款 vs 收藏款
    lines.append("## ⚡ 传播款 vs 收藏款 ROI")
    lines.append("")
    lines.append("| 类型 | 条数 | 均播放量 | 均互动率 | 均完播率 | 均涨粉效率 | 总涨粉 |")
    lines.append("|------|------|----------|----------|----------|------------|--------|")
    for ctype, stats in type_analysis.items():
        cr = f"{stats.get('avg_completion_rate', 0):.1%}" if stats.get('avg_completion_rate') else "N/A"
        fe = f"{stats.get('avg_follower_efficiency', 0):.1f}/万播" if stats.get('avg_follower_efficiency') else "N/A"
        lines.append(
            f"| {ctype} | {stats['count']} | {stats['avg_views']:,} | "
            f"{stats.get('avg_engagement_rate', 0):.2%} | {cr} | {fe} | {stats['total_followers']:,} |"
        )
    lines.append("")

    # 最佳发布时间
    if best_times:
        lines.append("## ⏰ 最佳发布时间段")
        lines.append("")
        lines.append("| 时段 | 内容数 | 平均播放量 |")
        lines.append("|------|--------|------------|")
        for slot in best_times:
            lines.append(f"| {slot['time_slot']} | {slot['count']} | {slot['avg_views']:,} |")
        lines.append("")
        top_slot = best_times[0]["time_slot"] if best_times else "未知"
        lines.append(f"> **建议**: 最优发布时段为 **{top_slot}**，平均播放量最高")
        lines.append("")

    # 涨粉效率趋势
    lines.append("## 📈 涨粉效率趋势")
    lines.append("")
    lines.append("| 日期 | 标题 | 播放量 | 新增粉丝 | 涨粉效率 |")
    lines.append("|------|------|--------|----------|----------|")
    for t in follower_trend:
        fe = f"{t['follower_efficiency']:.1f}/万播"
        lines.append(f"| {t['date']} | {t['title']} | {t['views']:,} | {t['followers_gained']:,} | {fe} |")
    lines.append("")

    report = "\n".join(lines)

    # 保存
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path_obj, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[OK] 周期报告生成: {output_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="生成周报/月报复盘分析")
    parser.add_argument("--data", "-d", required=True, help="content_data.json文件路径")
    parser.add_argument("--period", "-p", choices=["week", "month", "quarter"], default=None,
                        help="预设时间范围（week/month/quarter）")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD（自定义范围）")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD（自定义范围）")
    parser.add_argument("--output", "-o", default="period_report.md", help="输出Markdown文件路径")
    args = parser.parse_args()

    if not args.period and not (args.start and args.end):
        print("[WARN] 未指定时间范围，将分析全部数据")

    try:
        analyze_period(args.data, args.period, args.start, args.end, args.output)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
