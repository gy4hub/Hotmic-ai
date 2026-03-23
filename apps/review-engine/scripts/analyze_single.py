#!/usr/bin/env python3
"""
analyze_single.py — 单条内容复盘分析

对内容数据集中的某一条内容进行深度复盘，生成：
- 数据概览（绝对值 + 行业基准对比）
- 同类内容对比（同平台、同content_type的均值）
- 表现归因分析（标题、选题类型、发布时间、完播率分析）

用法:
  python analyze_single.py --data content_data.json --id 0 --output report.md
  python analyze_single.py --data content_data.json --title "315点名的外泌体" --output report.md
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


# 行业基准值（参考 references/metrics_guide.md）
BENCHMARKS = {
    "engagement_rate": {"excellent": 0.05, "good": 0.03, "average": 0.01},
    "completion_rate": {"excellent": 0.60, "good": 0.40, "average": 0.25},
    "follower_efficiency": {"excellent": 20, "good": 10, "average": 5},  # 每万播放涨粉数
    "share_rate": {"excellent": 0.007, "good": 0.005, "average": 0.003}
}


def compute_metrics(entry: dict) -> dict:
    """
    计算单条内容的核心指标。

    Args:
        entry: 单条内容数据

    Returns:
        计算后的指标字典
    """
    views = entry.get("views") or 0
    likes = entry.get("likes") or 0
    comments = entry.get("comments") or 0
    shares = entry.get("shares") or 0
    followers = entry.get("followers_gained") or 0
    saves = entry.get("saves") or 0
    completion = entry.get("completion_rate")

    metrics = {}

    # 互动率
    if views > 0:
        metrics["engagement_rate"] = round((likes + comments + shares) / views, 4)
        metrics["share_rate"] = round(shares / views, 4)
        metrics["follower_efficiency"] = round(followers / views * 10000, 2)
        if saves:
            metrics["save_rate"] = round(saves / views, 4)
    else:
        metrics["engagement_rate"] = 0
        metrics["share_rate"] = 0
        metrics["follower_efficiency"] = 0

    metrics["completion_rate"] = completion

    return metrics


def grade_metric(value: float | None, metric_name: str) -> str:
    """
    对指标打等级（优秀/良好/平均/较差）。
    """
    if value is None:
        return "数据缺失"
    benchmarks = BENCHMARKS.get(metric_name, {})
    if not benchmarks:
        return "N/A"

    if value >= benchmarks.get("excellent", float('inf')):
        return "🟢 优秀"
    elif value >= benchmarks.get("good", float('inf')):
        return "🔵 良好"
    elif value >= benchmarks.get("average", float('inf')):
        return "🟡 平均"
    else:
        return "🔴 较差"


def find_peer_entries(entry: dict, all_entries: list[dict]) -> list[dict]:
    """
    找到同类内容（同content_type）进行对比。
    至少需要2条同类才进行对比，否则用全部内容。
    """
    content_type = entry.get("content_type")
    if not content_type:
        return [e for e in all_entries if e != entry]

    peers = [e for e in all_entries
             if e.get("content_type") == content_type and e != entry]
    return peers if len(peers) >= 2 else all_entries


def compute_average_metrics(entries: list[dict]) -> dict:
    """计算一组内容的平均指标。"""
    if not entries:
        return {}

    all_metrics = [compute_metrics(e) for e in entries]

    avg = {}
    for key in ["engagement_rate", "share_rate", "follower_efficiency", "completion_rate"]:
        values = [m[key] for m in all_metrics if m.get(key) is not None]
        if values:
            avg[key] = round(sum(values) / len(values), 4)

    views = [e.get("views") for e in entries if e.get("views")]
    if views:
        avg["avg_views"] = round(sum(views) / len(views))

    return avg


def attribute_performance(entry: dict, metrics: dict, peer_avg: dict) -> list[str]:
    """
    表现归因分析：从标题、选题、发布时间等维度分析原因。
    """
    attributions = []

    views = entry.get("views") or 0
    title = entry.get("title", "")
    publish_time = entry.get("publish_time", "")
    content_type = entry.get("content_type", "")

    # 标题分析
    has_number = any(c.isdigit() for c in title)
    has_question = "？" in title or "吗" in title or "为什么" in title or "如何" in title
    has_negative = "别" in title or "不要" in title or "坑" in title or "骗" in title or "315" in title

    if has_number:
        attributions.append("✅ 标题含具体数字，有助于提升CTR（点击率）")
    if has_question:
        attributions.append("✅ 标题使用疑问句式，容易引发用户好奇心")
    if has_negative:
        attributions.append("✅ 标题含负面/拦截关键词（坑/骗/别），传播潜力强")

    # 完播率归因
    cr = metrics.get("completion_rate")
    peer_cr = peer_avg.get("completion_rate")
    if cr and peer_cr:
        if cr > peer_cr * 1.2:
            attributions.append(f"✅ 完播率（{cr:.0%}）显著高于同类均值（{peer_cr:.0%}），内容结构吸引人")
        elif cr < peer_cr * 0.8:
            attributions.append(f"⚠️ 完播率（{cr:.0%}）低于同类均值（{peer_cr:.0%}），建议检查开头留存钩子")

    # 发布时间分析
    if publish_time:
        try:
            hour = int(publish_time.split(":")[0])
            if 19 <= hour <= 22:
                attributions.append(f"✅ 发布时间（{publish_time}）处于晚间黄金时段")
            elif 7 <= hour <= 9:
                attributions.append(f"✅ 发布时间（{publish_time}）为早间通勤时段，适合时事内容")
            elif hour < 6 or hour > 23:
                attributions.append(f"⚠️ 发布时间（{publish_time}）较偏，建议移至19:00-22:00")
        except (ValueError, IndexError):
            pass

    # 内容类型归因
    er = metrics.get("engagement_rate") or 0
    if content_type == "传播款":
        if metrics.get("share_rate", 0) > BENCHMARKS["share_rate"]["good"]:
            attributions.append(f"✅ 分享率（{metrics['share_rate']:.2%}）达到传播款良好基准，话题具有扩散性")
        else:
            attributions.append(f"⚠️ 作为传播款，分享率（{metrics.get('share_rate', 0):.2%}）偏低，话题传播力有待提升")
    elif content_type == "收藏款":
        if metrics.get("follower_efficiency", 0) > BENCHMARKS["follower_efficiency"]["good"]:
            attributions.append(f"✅ 涨粉效率（{metrics.get('follower_efficiency', 0):.1f}/万播）达到收藏款良好基准")

    if not attributions:
        attributions.append("暂无明显的正面或负面归因，建议与更多历史数据对比")

    return attributions


def analyze_single(
    data_path: str,
    entry_id: int | None,
    entry_title: str | None,
    output_path: str
) -> str:
    """
    单条复盘主流程。

    Args:
        data_path: content_data.json路径
        entry_id: 条目索引（从0开始）
        entry_title: 条目标题（与entry_id二选一）
        output_path: 输出Markdown路径

    Returns:
        Markdown报告字符串
    """
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    platform = data.get("platform", "未知")

    if not entries:
        raise ValueError("数据文件中没有内容条目")

    # 找到目标条目
    if entry_id is not None:
        if entry_id >= len(entries):
            raise ValueError(f"entry_id={entry_id} 超出范围，共 {len(entries)} 条数据")
        entry = entries[entry_id]
    elif entry_title:
        entry = next((e for e in entries if entry_title in e.get("title", "")), None)
        if not entry:
            raise ValueError(f"未找到标题包含 '{entry_title}' 的条目")
    else:
        raise ValueError("请提供 --id 或 --title 参数")

    # 计算指标
    metrics = compute_metrics(entry)

    # 找同类做对比
    peers = find_peer_entries(entry, entries)
    peer_avg = compute_average_metrics(peers)

    # 归因分析
    attributions = attribute_performance(entry, metrics, peer_avg)

    # 生成报告
    lines = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = entry.get("title", "未命名")
    date = entry.get("date", "未知日期")

    lines.append(f"# 单条复盘报告：{title}")
    lines.append("")
    lines.append(f"**发布日期**: {date} | **平台**: {platform} | **生成时间**: {now}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 数据概览
    lines.append("## 📊 数据概览")
    lines.append("")
    lines.append("| 指标 | 数值 | 评级 |")
    lines.append("|------|------|------|")
    lines.append(f"| 播放量 | {entry.get('views', 'N/A'):,} | — |")
    lines.append(f"| 互动率 | {metrics.get('engagement_rate', 0):.2%} | {grade_metric(metrics.get('engagement_rate'), 'engagement_rate')} |")
    lines.append(f"| 完播率 | {(metrics.get('completion_rate') or 0):.2%} | {grade_metric(metrics.get('completion_rate'), 'completion_rate')} |")
    lines.append(f"| 分享率 | {metrics.get('share_rate', 0):.2%} | {grade_metric(metrics.get('share_rate'), 'share_rate')} |")
    lines.append(f"| 涨粉效率 | {metrics.get('follower_efficiency', 0):.1f}/万播 | {grade_metric(metrics.get('follower_efficiency'), 'follower_efficiency')} |")
    lines.append(f"| 点赞数 | {(entry.get('likes') or 0):,} | — |")
    lines.append(f"| 评论数 | {(entry.get('comments') or 0):,} | — |")
    lines.append(f"| 分享数 | {(entry.get('shares') or 0):,} | — |")
    lines.append(f"| 新增粉丝 | {(entry.get('followers_gained') or 0):,} | — |")
    lines.append("")

    # 同类对比
    if peer_avg and peers:
        lines.append("## 📈 同类内容对比")
        lines.append("")
        content_type = entry.get("content_type", "全部")
        lines.append(f"> 与 **{len(peers)}** 条同类型（{content_type}）内容的均值对比")
        lines.append("")
        lines.append("| 指标 | 本条 | 同类均值 | 差距 |")
        lines.append("|------|------|----------|------|")

        def fmt_diff(val, avg):
            if val is None or avg is None or avg == 0:
                return "N/A"
            diff = (val - avg) / avg
            prefix = "+" if diff >= 0 else ""
            return f"{prefix}{diff:.1%}"

        lines.append(f"| 播放量 | {(entry.get('views') or 0):,} | {peer_avg.get('avg_views', 0):,.0f} | {fmt_diff(entry.get('views'), peer_avg.get('avg_views'))} |")
        lines.append(f"| 互动率 | {metrics.get('engagement_rate', 0):.2%} | {peer_avg.get('engagement_rate', 0):.2%} | {fmt_diff(metrics.get('engagement_rate'), peer_avg.get('engagement_rate'))} |")
        lines.append(f"| 完播率 | {(metrics.get('completion_rate') or 0):.2%} | {peer_avg.get('completion_rate', 0):.2%} | {fmt_diff(metrics.get('completion_rate'), peer_avg.get('completion_rate'))} |")
        lines.append(f"| 分享率 | {metrics.get('share_rate', 0):.2%} | {peer_avg.get('share_rate', 0):.2%} | {fmt_diff(metrics.get('share_rate'), peer_avg.get('share_rate'))} |")
        lines.append("")

    # 归因分析
    lines.append("## 🔍 表现归因分析")
    lines.append("")
    for attr in attributions:
        lines.append(f"- {attr}")
    lines.append("")

    # 元数据
    lines.append("---")
    lines.append("")
    lines.append("## 📋 内容元数据")
    lines.append("")
    lines.append(f"- **内容主线**: {entry.get('content_line', '未填写')}")
    lines.append(f"- **内容类型**: {entry.get('content_type', '未填写')}")
    lines.append(f"- **发布时间**: {entry.get('publish_time', '未填写')}")
    lines.append("")

    report = "\n".join(lines)

    # 保存
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path_obj, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[OK] 单条复盘报告: {output_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="生成单条内容复盘报告")
    parser.add_argument("--data", "-d", required=True, help="content_data.json文件路径")
    parser.add_argument("--id", "-i", type=int, default=None, help="条目索引（从0开始）")
    parser.add_argument("--title", "-t", default=None, help="按标题查找条目（部分匹配）")
    parser.add_argument("--output", "-o", default="single_report.md", help="输出Markdown文件路径")
    args = parser.parse_args()

    if args.id is None and args.title is None:
        parser.error("需要提供 --id 或 --title")

    try:
        analyze_single(args.data, args.id, args.title, args.output)
    except (ValueError, FileNotFoundError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
