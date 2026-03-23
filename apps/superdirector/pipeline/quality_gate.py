from __future__ import annotations

import re
from statistics import mean
from typing import Any


ENGLISH_RE = re.compile(r"[a-zA-Z]")


def _get_score(topic: Any) -> float | None:
    value = getattr(topic, "score_total", None)
    if value is None and isinstance(topic, dict):
        value = topic.get("score_total")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _get_source(topic: Any) -> str:
    value = getattr(topic, "source", None)
    if value is None and isinstance(topic, dict):
        value = topic.get("source")
    return str(value or "").strip()


def _get_title(topic: Any) -> str:
    value = getattr(topic, "title", None)
    if value is None and isinstance(topic, dict):
        value = topic.get("title")
    return str(value or "").strip()


def _get_field(topic: Any, field: str) -> str:
    value = getattr(topic, field, None)
    if value is None and isinstance(topic, dict):
        value = topic.get(field)
    return str(value or "").strip()


def _is_official_style(topic: Any) -> bool:
    source = _get_source(topic)
    title = _get_title(topic).lower()
    if source not in {"nmpa_news", "govcn_policy", "fda_safety", "who_alerts"}:
        return False
    return any(token in title for token in ("notice", "meets with", "commissioner", "发布", "通报", "会见", "召开"))


def quality_gate(topics: list[Any], raw_item_count: int) -> tuple[bool, str]:
    if raw_item_count < 5:
        return False, f"信源不足: 仅采集到 {raw_item_count} 条，阈值 5"

    if not topics:
        return False, "无评分结果"

    has_editorial_fields = any(_get_field(topic, "topic_line_primary") for topic in topics)
    if has_editorial_fields:
        ranked = list(topics[:3])
    else:
        ranked = sorted(topics, key=lambda topic: _get_score(topic) or 0.0, reverse=True)[:3]
    if not ranked:
        return False, "无评分结果"

    scores = [_get_score(topic) for topic in ranked]
    if any(score is None for score in scores):
        return False, "无评分结果"

    avg = mean(score for score in scores if score is not None)
    if avg < 3.5:
        return False, f"平均分 {avg:.1f} 低于阈值 3.5"

    for topic in ranked:
        title = _get_title(topic)
        if not title:
            continue
        english_chars = len(ENGLISH_RE.findall(title))
        if english_chars / max(len(title), 1) > 0.5:
            return False, f"选题含未本地化英文标题: {title[:30]}"

    if not has_editorial_fields:
        sources = {source for source in (_get_source(topic) for topic in ranked) if source}
        if len(sources) == 1:
            return False, f"Top 3 全部来自 {sources.pop()}，信源单一"
        return True, "通过"

    lines = {_get_field(topic, "topic_line_primary") for topic in ranked if _get_field(topic, "topic_line_primary")}
    if len(lines) == 1:
        return False, f"Top 3 全部来自同一主线: {next(iter(lines))}"

    roles = {_get_field(topic, "content_role") for topic in ranked if _get_field(topic, "content_role")}
    if len(roles) == 1:
        return False, f"Top 3 全部属于同一内容角色: {next(iter(roles))}"

    clusters = {_get_field(topic, "topic_cluster") for topic in ranked if _get_field(topic, "topic_cluster")}
    if len(clusters) == 1:
        return False, f"Top 3 全部来自同一 topic_cluster: {next(iter(clusters))}"

    if not any(_get_field(topic, "topic_line_primary") in {"public_issue", "family_anxiety"} for topic in ranked):
        return False, "Top 3 缺少 public_issue / family_anxiety 主线"

    if all(_is_official_style(topic) for topic in ranked):
        return False, "Top 3 全部偏官方通稿风格"

    return True, "通过"
