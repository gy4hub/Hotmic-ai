from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean
from typing import Any
import re

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from compat import UTC
from db.models import PipelineRun, Topic
from pipeline.editorial import normalize_editorial_item, select_topics_for_output


def _topic_to_candidate(row: Topic) -> dict[str, Any]:
    keywords = []
    if row.keywords:
        try:
            import json

            parsed = json.loads(row.keywords)
            if isinstance(parsed, list):
                keywords = parsed
        except Exception:
            keywords = []
    payload = {
        "topic_id": row.topic_id,
        "title": row.title,
        "source": row.source,
        "summary": row.summary,
        "keywords": keywords,
        "score_total": row.score_total or 0.0,
        "quality_score": row.score_total or 0.0,
        "platform_priority": row.platform_priority,
        "url": row.url,
        "raw_snippet": row.raw_snippet,
        "manual_override_note": row.manual_override_note,
        "topic_line_primary": row.topic_line_primary,
        "topic_line_secondary": row.topic_line_secondary,
        "line_confidence": row.line_confidence,
        "content_role": row.content_role,
        "audience_core": row.audience_core,
        "compliance_risk": row.compliance_risk,
        "actionability_risk": row.actionability_risk,
        "topic_cluster": row.topic_cluster,
        "parent_topic_cluster": row.parent_topic_cluster,
        "series_anchor_id": row.series_anchor_id,
        "reject_type": row.reject_type,
        "rejection_reason": row.rejection_reason,
        "timeliness_window": row.timeliness_window,
        "platform_fit": row.platform_fit,
        "decision_impact_level": row.decision_impact_level,
        "selection_rank_reason": row.selection_rank_reason,
        "editorial_priority_score": row.editorial_priority_score,
    }
    if not row.topic_line_primary:
        payload.update(normalize_editorial_item(payload, payload))
    return payload


async def _topics_for_window(session: AsyncSession, *, start_at: datetime, end_at: datetime) -> list[Topic]:
    stmt = (
        select(Topic)
        .join(PipelineRun, Topic.pipeline_run_id == PipelineRun.id)
        .where(PipelineRun.started_at >= start_at)
        .where(PipelineRun.started_at <= end_at)
        .where(Topic.score_total.is_not(None))
        .order_by(PipelineRun.started_at.asc(), desc(Topic.score_total))
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


_TOPIC_ID_SUFFIX_RE = re.compile(r"_(\d+)$")


def _canonical_topic_key(topic: dict[str, Any]) -> str:
    topic_id = str(topic.get("topic_id") or "")
    base_topic_id = _TOPIC_ID_SUFFIX_RE.sub("", topic_id)
    title = " ".join(str(topic.get("title") or "").strip().lower().split())
    if base_topic_id:
        return base_topic_id
    if title:
        return title
    return topic_id or "unknown"


def _dedupe_daily_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = _canonical_topic_key(candidate)
        current = best_by_key.get(key)
        candidate_score = float(candidate.get("score_total") or 0.0)
        current_score = float(current.get("score_total") or 0.0) if current else float("-inf")
        if current is None or candidate_score > current_score:
            best_by_key[key] = candidate
    return sorted(best_by_key.values(), key=lambda item: float(item.get("score_total") or 0.0), reverse=True)


def _summarize_topics(topics: list[dict[str, Any]]) -> dict[str, Any]:
    line_counts = Counter(str(topic.get("topic_line_primary") or "") for topic in topics)
    role_counts = Counter(str(topic.get("content_role") or "") for topic in topics)
    cluster_counts = Counter(str(topic.get("topic_cluster") or "") for topic in topics)
    source_counts = Counter(str(topic.get("source") or "") for topic in topics)
    risk_counts = Counter(
        "high"
        if topic.get("compliance_risk") == "high" or topic.get("actionability_risk") == "high"
        else "medium"
        if topic.get("compliance_risk") == "medium" or topic.get("actionability_risk") == "medium"
        else "low"
        for topic in topics
    )
    avg_quality = round(mean(float(topic.get("score_total") or 0.0) for topic in topics), 4) if topics else 0.0
    return {
        "line_distribution": dict(line_counts),
        "role_distribution": dict(role_counts),
        "cluster_repetition_rate": round(
            sum(count - 1 for count in cluster_counts.values() if count > 1) / max(len(topics), 1),
            4,
        ),
        "source_concentration": dict(source_counts),
        "risk_distribution": dict(risk_counts),
        "avg_quality_score": avg_quality,
    }


def _selection_metrics(days: list[list[dict[str, Any]]]) -> dict[str, Any]:
    total_days = len(days)
    line_diversity_pass_days = 0
    role_diversity_pass_days = 0
    cluster_diversity_pass_days = 0
    public_or_family_days = 0
    high_risk_selected_count = 0
    rejected_selected_count = 0
    avg_day_top_score = 0.0
    if total_days:
        avg_day_top_score = round(
            mean(max(float(topic.get("score_total") or 0.0) for topic in day) if day else 0.0 for day in days),
            4,
        )

    for day in days:
        lines = {str(topic.get("topic_line_primary") or "") for topic in day if topic.get("topic_line_primary")}
        roles = {str(topic.get("content_role") or "") for topic in day if topic.get("content_role")}
        clusters = {str(topic.get("topic_cluster") or "") for topic in day if topic.get("topic_cluster")}
        if len(lines) >= 2:
            line_diversity_pass_days += 1
        if len(roles) >= 2:
            role_diversity_pass_days += 1
        if len(clusters) >= 2:
            cluster_diversity_pass_days += 1
        if any(str(topic.get("topic_line_primary") or "") in {"public_issue", "family_anxiety"} for topic in day):
            public_or_family_days += 1
        high_risk_selected_count += sum(
            1
            for topic in day
            if topic.get("compliance_risk") == "high" or topic.get("actionability_risk") == "high"
        )
        rejected_selected_count += sum(
            1
            for topic in day
            if str(topic.get("reject_type") or "none") != "none"
            or str(topic.get("topic_line_primary") or "") == "rejected"
        )

    return {
        "days": total_days,
        "line_diversity_pass_rate": round(line_diversity_pass_days / max(total_days, 1), 4),
        "role_diversity_pass_rate": round(role_diversity_pass_days / max(total_days, 1), 4),
        "cluster_diversity_pass_rate": round(cluster_diversity_pass_days / max(total_days, 1), 4),
        "public_or_family_coverage_rate": round(public_or_family_days / max(total_days, 1), 4),
        "high_risk_selected_count": high_risk_selected_count,
        "rejected_selected_count": rejected_selected_count,
        "avg_day_top_score": avg_day_top_score,
    }


def _daily_replay(date_key: str, old_selected: list[dict[str, Any]], new_selected: list[dict[str, Any]]) -> dict[str, Any]:
    old_titles = [str(topic.get("title") or "") for topic in old_selected]
    new_titles = [str(topic.get("title") or "") for topic in new_selected]
    return {
        "date": date_key,
        "old_titles": old_titles,
        "new_titles": new_titles,
        "changed_slots": sum(1 for old, new in zip(old_titles, new_titles) if old != new),
        "old_lines": [str(topic.get("topic_line_primary") or "") for topic in old_selected],
        "new_lines": [str(topic.get("topic_line_primary") or "") for topic in new_selected],
        "old_roles": [str(topic.get("content_role") or "") for topic in old_selected],
        "new_roles": [str(topic.get("content_role") or "") for topic in new_selected],
    }


async def run_editorial_backtest(session: AsyncSession) -> dict[str, Any]:
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    three_months_ago = now - timedelta(days=90)
    one_year_ago = now - timedelta(days=365)

    recent_rows = await _topics_for_window(session, start_at=three_months_ago, end_at=now)
    long_rows = await _topics_for_window(session, start_at=one_year_ago, end_at=three_months_ago)

    recent_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in recent_rows:
        recent_groups[str(row.date or row.created_at.date())].append(_topic_to_candidate(row))

    historical_context: list[dict[str, Any]] = []
    old_selected_all: list[dict[str, Any]] = []
    new_selected_all: list[dict[str, Any]] = []
    old_daily: list[list[dict[str, Any]]] = []
    new_daily: list[list[dict[str, Any]]] = []
    old_titles: set[str] = set()
    new_titles: set[str] = set()
    replays: list[dict[str, Any]] = []

    for date_key in sorted(recent_groups.keys()):
        candidates = _dedupe_daily_candidates(recent_groups[date_key])
        old_ranked = sorted(candidates, key=lambda item: float(item.get("score_total") or 0.0), reverse=True)[:3]
        editorial_ranked, _meta = select_topics_for_output(candidates, historical_context, phase=2, top_n=3)
        old_selected_all.extend(old_ranked)
        new_selected_all.extend(editorial_ranked)
        old_daily.append(old_ranked)
        new_daily.append(editorial_ranked)
        old_titles.update(str(item.get("title") or "") for item in old_ranked)
        new_titles.update(str(item.get("title") or "") for item in editorial_ranked)
        historical_context.extend(editorial_ranked)
        replays.append(_daily_replay(date_key, old_ranked, editorial_ranked))

    available_days = sorted(recent_groups.keys())
    history_days = len(available_days)
    insufficient_history = history_days < 14

    return {
        "windows": {
            "recent_3m_topics": len(recent_rows),
            "historical_6_12m_sample_topics": len(long_rows),
            "recent_available_days": history_days,
            "recent_available_dates": available_days,
            "insufficient_history": insufficient_history,
            "history_note": "近 14 天以下的数据更适合做方向观察，不适合下结论。" if insufficient_history else "样本量可用于阶段性回测。",
        },
        "comparison": {
            "old_vs_new_title_overlap": len(old_titles & new_titles),
            "new_unique_titles": len(new_titles - old_titles),
            "old_unique_titles": len(old_titles - new_titles),
        },
        "old_system": _summarize_topics(old_selected_all),
        "new_system": _summarize_topics(new_selected_all),
        "old_metrics": _selection_metrics(old_daily),
        "new_metrics": _selection_metrics(new_daily),
        "daily_replays": replays,
    }
