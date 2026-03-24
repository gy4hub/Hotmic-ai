import json
from datetime import datetime, timedelta
from typing import Any, Iterable
from sqlalchemy import select, update, delete, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from compat import UTC
from db.models import (
    PipelineRun,
    Topic,
    ScoreDetail,
    ApiCostLog,
    SystemLog,
    BitableSyncTask,
    ScheduleJob,
    PlatformFeedback,
    RawCandidate,
)


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _utc_now() -> datetime:
    # Keep DB timestamps stored as naive UTC to match the existing SQLite schema.
    return datetime.now(UTC).replace(tzinfo=None)


def _topic_values(t: dict) -> dict:
    return {
        "topic_id": t.get("topic_id"),
        "date": t.get("date"),
        "title": t.get("title"),
        "original_title": t.get("original_title"),
        "localized_title": t.get("localized_title"),
        "angle_type": t.get("angle_type"),
        "platform_priority": t.get("platform_priority"),
        "content_type": t.get("content_type"),
        "status": t.get("status", "ok"),
        "url": t.get("url"),
        "source": t.get("source"),
        "timestamp": t.get("timestamp"),
        "raw_snippet": t.get("raw_snippet"),
        "summary": t.get("summary"),
        "keywords": _json_dumps(t.get("keywords")),
        "competitor_angle": t.get("competitor_angle"),
        "angle_gap": t.get("angle_gap"),
        "topic_line_primary": t.get("topic_line_primary"),
        "topic_line_secondary": t.get("topic_line_secondary"),
        "line_confidence": t.get("line_confidence"),
        "content_role": t.get("content_role"),
        "creator_fit": t.get("creator_fit"),
        "li_jie_value": t.get("li_jie_value"),
        "zhang_auntie_value": t.get("zhang_auntie_value"),
        "audience_core": t.get("audience_core"),
        "compliance_risk": t.get("compliance_risk"),
        "actionability_risk": t.get("actionability_risk"),
        "topic_cluster": t.get("topic_cluster"),
        "cluster_mismatch": 1 if t.get("cluster_mismatch") else 0,
        "parent_topic_cluster": t.get("parent_topic_cluster"),
        "series_anchor_id": t.get("series_anchor_id"),
        "reject_type": t.get("reject_type"),
        "rejection_reason": t.get("rejection_reason"),
        "timeliness_window": t.get("timeliness_window"),
        "platform_fit": t.get("platform_fit"),
        "decision_impact_level": t.get("decision_impact_level"),
        "manual_override_note": t.get("manual_override_note"),
        "selection_rank_reason": t.get("selection_rank_reason"),
        "editorial_priority_score": t.get("editorial_priority_score"),
        "score_total": t.get("score_total"),
        "score_emotion": t.get("score_emotion"),
        "score_timely": t.get("score_timely"),
        "score_subvert": t.get("score_subvert"),
        "score_relate": t.get("score_relate"),
        "score_spread": t.get("score_spread"),
        "score_tension": t.get("score_tension"),
        "score_depth": t.get("score_depth"),
        "search_terms": t.get("search_terms"),
        "search_queries": t.get("search_queries"),
        "search_sources": t.get("search_sources"),
        "monetize_goods": t.get("monetize_goods"),
        "monetize_course": t.get("monetize_course"),
        "monetize_notes": t.get("monetize_notes"),
        "creator_ops": t.get("creator_ops"),
        "creator_notes": t.get("creator_notes"),
        "publish_match_terms": t.get("publish_match_terms"),
        "review_status": t.get("review_status"),
        "publish_status": t.get("publish_status"),
        "publish_url": t.get("publish_url"),
        "publish_at": t.get("publish_at"),
        "perf_views": t.get("perf_views"),
        "perf_likes": t.get("perf_likes"),
        "perf_collects": t.get("perf_collects"),
        "perf_watch_rate": t.get("perf_watch_rate"),
        "perf_favorite_rate": t.get("perf_favorite_rate"),
        "perf_comments": t.get("perf_comments"),
        "perf_shares": t.get("perf_shares"),
        "pipeline_run_id": t.get("pipeline_run_id"),
        "model_version": t.get("model_version"),
        "errors_json": _json_dumps(t.get("errors")),
        "frame_json": _json_dumps(t.get("frame")),
        "frame_status": t.get("frame_status"),
        "frame_tier": t.get("frame_tier"),
        "frame_rejection_reason": t.get("frame_rejection_reason"),
        "updated_at": _utc_now(),
    }


async def create_pipeline_run(session: AsyncSession) -> PipelineRun:
    run = PipelineRun(status="running", started_at=_utc_now())
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def fail_stale_pipeline_runs(
    session: AsyncSession,
    *,
    stale_after_seconds: int,
) -> int:
    cutoff = _utc_now() - timedelta(seconds=max(stale_after_seconds, 1))
    stmt = (
        update(PipelineRun)
        .where(PipelineRun.status == "running")
        .where(PipelineRun.started_at < cutoff)
        .values(
            finished_at=_utc_now(),
            status="failed",
            error_count=1,
            errors_json=_json_dumps(
                [
                    f"Pipeline run exceeded timeout ({stale_after_seconds}s) and was auto-closed."
                ]
            ),
        )
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount or 0


async def finalize_pipeline_run(
    session: AsyncSession,
    run_id: int,
    status: str,
    topics_count: int,
    raw_item_count: int,
    error_count: int,
    total_tokens: int | None,
    total_cost: float | None,
    errors: list[str] | None,
) -> None:
    stmt = (
        update(PipelineRun)
        .where(PipelineRun.id == run_id)
        .values(
            finished_at=_utc_now(),
            status=status,
            topics_count=topics_count,
            raw_item_count=raw_item_count,
            error_count=error_count,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            errors_json=_json_dumps(errors),
        )
    )
    await session.execute(stmt)
    await session.commit()


async def insert_topics(session: AsyncSession, topics: Iterable[dict]) -> list[Topic]:
    rows: list[Topic] = []
    for t in topics:
        topic_id = t.get("topic_id")
        existing = None
        if topic_id:
            result = await session.execute(select(Topic).where(Topic.topic_id == topic_id))
            existing = result.scalar_one_or_none()

        values = _topic_values(t)
        if existing:
            if existing.pipeline_run_id == values.get("pipeline_run_id"):
                for key, value in values.items():
                    setattr(existing, key, value)
                rows.append(existing)
            else:
                run_id = values.get("pipeline_run_id") or "rerun"
                values["topic_id"] = f"{topic_id}_{run_id}"
                row = Topic(**values)
                session.add(row)
                rows.append(row)
        else:
            row = Topic(**values)
            session.add(row)
            rows.append(row)

    await session.commit()
    for row in rows:
        await session.refresh(row)
    return rows


async def insert_score_details(session: AsyncSession, details: Iterable[dict]) -> None:
    for d in details:
        row = ScoreDetail(
            topic_id=d.get("topic_id"),
            dimension=d.get("dimension"),
            raw_score=d.get("raw_score"),
            weighted_score=d.get("weighted_score"),
            platform=d.get("platform"),
            weight_version=d.get("weight_version"),
        )
        session.add(row)
    await session.commit()


async def log_cost(
    session: AsyncSession,
    provider: str,
    model: str,
    endpoint: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cost_usd: float | None,
) -> None:
    row = ApiCostLog(
        provider=provider,
        model=model,
        endpoint=endpoint,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    session.add(row)
    await session.commit()


async def log_system(
    session: AsyncSession,
    level: str,
    module: str,
    message: str,
    details: dict | None = None,
) -> None:
    row = SystemLog(
        level=level,
        module=module,
        message=message,
        details_json=_json_dumps(details),
    )
    session.add(row)
    await session.commit()


async def get_today_topics(session: AsyncSession, date_str: str) -> list[Topic]:
    stmt = (
        select(Topic)
        .where(Topic.date == date_str)
        .order_by(desc(func.coalesce(Topic.editorial_priority_score, Topic.score_total)), desc(Topic.score_total))
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_latest_completed_run(
    session: AsyncSession,
    *,
    date_str: str | None = None,
) -> PipelineRun | None:
    stmt = (
        select(PipelineRun)
        .where(PipelineRun.status.in_(("ok", "partial")))
        .where(PipelineRun.topics_count > 0)
        .order_by(desc(PipelineRun.id))
    )
    if date_str:
        stmt = stmt.where(func.date(PipelineRun.started_at) == date_str)  # type: ignore[name-defined]
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none()


async def get_latest_briefing_run(
    session: AsyncSession,
    *,
    date_str: str | None = None,
) -> PipelineRun | None:
    stmt = (
        select(PipelineRun)
        .where(PipelineRun.status.in_(("ok", "partial", "quality_gate_failed")))
        .where(PipelineRun.topics_count > 0)
        .order_by(desc(PipelineRun.id))
    )
    if date_str:
        stmt = stmt.where(func.date(PipelineRun.started_at) == date_str)  # type: ignore[name-defined]
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none()


async def get_topics_for_run(
    session: AsyncSession,
    run_id: int,
    *,
    limit: int | None = None,
) -> list[Topic]:
    stmt = (
        select(Topic)
        .where(Topic.pipeline_run_id == run_id)
        .order_by(desc(func.coalesce(Topic.editorial_priority_score, Topic.score_total)), desc(Topic.score_total))
    )
    if limit:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_output_topics_for_run(
    session: AsyncSession,
    run_id: int,
    *,
    limit: int | None = None,
) -> list[Topic]:
    stmt = (
        select(Topic)
        .where(Topic.pipeline_run_id == run_id)
        .where(Topic.reject_type.is_(None) | (Topic.reject_type == "none"))
        .where(Topic.selection_rank_reason.is_not(None))
        .order_by(desc(func.coalesce(Topic.editorial_priority_score, Topic.score_total)), desc(Topic.score_total))
    )
    if limit:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_topic_by_topic_id(session: AsyncSession, topic_id: str) -> Topic | None:
    result = await session.execute(select(Topic).where(Topic.topic_id == topic_id))
    return result.scalar_one_or_none()


async def get_recent_top_topics(
    session: AsyncSession,
    *,
    since_days: int,
    limit: int,
) -> list[Topic]:
    cutoff = _utc_now() - timedelta(days=max(since_days, 1))
    stmt = (
        select(Topic)
        .join(PipelineRun, Topic.pipeline_run_id == PipelineRun.id)
        .where(PipelineRun.status.in_(("ok", "partial")))
        .where(PipelineRun.topics_count > 0)
        .where(PipelineRun.started_at >= cutoff)
        .order_by(desc(func.coalesce(Topic.editorial_priority_score, Topic.score_total)), desc(Topic.updated_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_recent_editorial_topics(
    session: AsyncSession,
    *,
    since_days: int,
    limit: int = 200,
) -> list[Topic]:
    cutoff = _utc_now() - timedelta(days=max(since_days, 1))
    stmt = (
        select(Topic)
        .join(PipelineRun, Topic.pipeline_run_id == PipelineRun.id)
        .where(PipelineRun.status.in_(("ok", "partial", "quality_gate_failed")))
        .where(PipelineRun.started_at >= cutoff)
        .order_by(desc(Topic.updated_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_recent_cluster_analysis(
    session: AsyncSession,
    cluster: str,
    *,
    days: int = 7,
) -> Topic | None:
    cluster_name = str(cluster or "").strip()
    if not cluster_name:
        return None
    cutoff = _utc_now() - timedelta(days=max(days, 1))
    stmt = (
        select(Topic)
        .where(Topic.topic_cluster == cluster_name)
        .where(Topic.updated_at >= cutoff)
        .order_by(desc(Topic.updated_at))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_topic_feedback(
    session: AsyncSession,
    topic_id: str,
    feedback: dict,
) -> Topic | None:
    result = await session.execute(select(Topic).where(Topic.topic_id == topic_id))
    row = result.scalar_one_or_none()
    if not row:
        return None

    for key, value in feedback.items():
        if hasattr(row, key):
            setattr(row, key, value)
    row.updated_at = _utc_now()
    await session.commit()
    await session.refresh(row)
    return row


async def update_topic_scoring(
    session: AsyncSession,
    topic_id: str,
    *,
    score_total: float,
    platform_priority: str | None,
) -> Topic | None:
    row = await get_topic_by_topic_id(session, topic_id)
    if not row:
        return None
    row.score_total = score_total
    row.platform_priority = platform_priority
    row.updated_at = _utc_now()
    await session.commit()
    await session.refresh(row)
    return row


async def replace_feedback_score_details(
    session: AsyncSession,
    topic_db_id: int,
    metrics: dict[str, float | int | None],
    *,
    platform: str | None,
    weight_version: str = "feedback_v1",
) -> None:
    dimensions = tuple(metrics.keys())
    if dimensions:
        stmt = delete(ScoreDetail).where(
            ScoreDetail.topic_id == topic_db_id,
            ScoreDetail.weight_version == weight_version,
            ScoreDetail.dimension.in_(dimensions),
        )
        await session.execute(stmt)

    for dimension, value in metrics.items():
        if value is None:
            continue
        row = ScoreDetail(
            topic_id=topic_db_id,
            dimension=dimension,
            raw_score=float(value),
            weighted_score=float(value),
            platform=platform,
            weight_version=weight_version,
        )
        session.add(row)
    await session.commit()


async def enqueue_bitable_sync_tasks(session: AsyncSession, tasks: Iterable[dict]) -> None:
    now = _utc_now()
    for task in tasks:
        row = BitableSyncTask(
            entity_type=task["entity_type"],
            entity_key=task["entity_key"],
            table_name=task["table_name"],
            payload_json=_json_dumps(task["payload"]) or "{}",
            status=task.get("status", "pending"),
            attempts=task.get("attempts", 0),
            error_message=task.get("error_message"),
            last_attempted_at=task.get("last_attempted_at"),
            created_at=task.get("created_at", now),
            updated_at=now,
        )
        session.add(row)
    await session.commit()


async def list_bitable_sync_tasks(
    session: AsyncSession,
    status: str = "pending",
    limit: int = 100,
) -> list[BitableSyncTask]:
    stmt = (
        select(BitableSyncTask)
        .where(BitableSyncTask.status == status)
        .order_by(BitableSyncTask.id.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_bitable_sync_tasks_done(session: AsyncSession, task_ids: Iterable[int]) -> None:
    ids = [task_id for task_id in task_ids if task_id]
    if not ids:
        return
    stmt = (
        update(BitableSyncTask)
        .where(BitableSyncTask.id.in_(ids))
        .values(
            status="synced",
            updated_at=_utc_now(),
            last_attempted_at=_utc_now(),
            error_message=None,
        )
    )
    await session.execute(stmt)
    await session.commit()


async def mark_bitable_sync_tasks_failed(
    session: AsyncSession,
    task_ids: Iterable[int],
    error_message: str,
) -> None:
    ids = [task_id for task_id in task_ids if task_id]
    if not ids:
        return
    stmt = (
        update(BitableSyncTask)
        .where(BitableSyncTask.id.in_(ids))
        .values(
            status="failed",
            attempts=BitableSyncTask.attempts + 1,
            updated_at=_utc_now(),
            last_attempted_at=_utc_now(),
            error_message=error_message,
        )
    )
    await session.execute(stmt)
    await session.commit()


def _utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def ensure_schedule_jobs(
    session: AsyncSession,
    jobs: Iterable[dict],
) -> list[ScheduleJob]:
    desired_ids = {job["job_id"] for job in jobs}
    await session.execute(delete(ScheduleJob).where(~ScheduleJob.job_id.in_(desired_ids)))
    rows: list[ScheduleJob] = []
    for job in jobs:
        row = await session.get(ScheduleJob, job["job_id"])
        if row is None:
            row = ScheduleJob(
                job_id=job["job_id"],
                cron_hour=job["cron_hour"],
                cron_minute=job["cron_minute"],
                enabled=1 if job.get("enabled", True) else 0,
                description=job.get("description"),
                updated_at=_utc_now_text(),
            )
            session.add(row)
        rows.append(row)
    await session.commit()
    return rows


async def list_schedule_jobs(session: AsyncSession) -> list[ScheduleJob]:
    result = await session.execute(select(ScheduleJob).order_by(ScheduleJob.job_id.asc()))
    return list(result.scalars().all())


async def get_schedule_job(session: AsyncSession, job_id: str) -> ScheduleJob | None:
    return await session.get(ScheduleJob, job_id)


async def update_schedule_job(
    session: AsyncSession,
    job_id: str,
    *,
    hour: int | None = None,
    minute: int | None = None,
    enabled: bool | None = None,
    description: str | None = None,
) -> ScheduleJob | None:
    row = await session.get(ScheduleJob, job_id)
    if row is None:
        return None
    if hour is not None:
        row.cron_hour = hour
    if minute is not None:
        row.cron_minute = minute
    if enabled is not None:
        row.enabled = 1 if enabled else 0
    if description is not None:
        row.description = description
    row.updated_at = _utc_now_text()
    await session.commit()
    await session.refresh(row)
    return row


async def update_schedule_job_run(
    session: AsyncSession,
    job_id: str,
    *,
    status: str,
    error: str | None = None,
) -> ScheduleJob | None:
    row = await session.get(ScheduleJob, job_id)
    if row is None:
        return None
    row.last_run_at = _utc_now_text()
    row.last_run_status = status
    row.last_run_error = error
    row.updated_at = _utc_now_text()
    await session.commit()
    await session.refresh(row)
    return row


async def list_topics_for_feedback(
    session: AsyncSession,
    *,
    platform: str,
    limit: int,
) -> list[Topic]:
    stmt = (
        select(Topic)
        .where(Topic.publish_url.is_not(None))
        .where(Topic.publish_url != "")
        .where(Topic.platform_priority == platform)
        .order_by(desc(Topic.publish_at), desc(Topic.updated_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_topics_for_publish_matching(
    session: AsyncSession,
    *,
    platform: str,
    limit: int = 200,
) -> list[Topic]:
    stmt = (
        select(Topic)
        .where(Topic.platform_priority == platform)
        .order_by(desc(Topic.updated_at), desc(Topic.created_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def upsert_platform_feedback(
    session: AsyncSession,
    payload: dict,
) -> PlatformFeedback:
    result = await session.execute(
        select(PlatformFeedback).where(
            PlatformFeedback.topic_id == payload["topic_id"],
            PlatformFeedback.platform == payload["platform"],
        )
    )
    row = result.scalar_one_or_none()
    values = {
        "video_id": payload.get("video_id"),
        "publish_url": payload["publish_url"],
        "status": payload.get("status", "ok"),
        "play_count": payload.get("play_count"),
        "digg_count": payload.get("digg_count"),
        "comment_count": payload.get("comment_count"),
        "collect_count": payload.get("collect_count"),
        "share_count": payload.get("share_count"),
        "completion_rate": payload.get("completion_rate"),
        "raw_json": _json_dumps(payload.get("raw")),
        "error_message": payload.get("error_message"),
        "collected_at": payload.get("collected_at", _utc_now()),
        "updated_at": _utc_now(),
    }
    if row is None:
        row = PlatformFeedback(
            topic_id=payload["topic_id"],
            platform=payload["platform"],
            **values,
        )
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return row


async def list_platform_feedback(
    session: AsyncSession,
    *,
    platform: str | None = None,
    limit: int = 100,
) -> list[PlatformFeedback]:
    stmt = select(PlatformFeedback).order_by(desc(PlatformFeedback.updated_at))
    if platform:
        stmt = stmt.where(PlatformFeedback.platform == platform)
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _raw_candidate_values(item: dict[str, Any], run_id: int) -> dict[str, Any]:
    title = str(item.get("title") or "").strip()
    url = str(item.get("url") or "").strip()
    source = str(item.get("source") or "").strip()
    timestamp = str(item.get("timestamp") or "").strip()
    snippet = str(item.get("raw_snippet") or item.get("snippet") or "").strip()
    fingerprint = str(item.get("fingerprint") or "").strip()
    return {
        "run_id": run_id,
        "source": source,
        "title": title,
        "url": url,
        "snippet": snippet,
        "published_at": timestamp,
        "fingerprint": fingerprint,
        "status": str(item.get("status") or "pending"),
        "collected_at": _utc_now(),
    }


async def insert_raw_candidates(
    session: AsyncSession,
    *,
    run_id: int,
    items: Iterable[dict[str, Any]],
) -> list[RawCandidate]:
    rows: list[RawCandidate] = []
    seen_fingerprints: set[str] = set()
    for item in items:
        values = _raw_candidate_values(item, run_id)
        fingerprint = values["fingerprint"]
        if fingerprint:
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            result = await session.execute(
                select(RawCandidate).where(
                    RawCandidate.fingerprint == fingerprint,
                    RawCandidate.status == "pending",
                )
            )
            if result.scalar_one_or_none():
                continue
        row = RawCandidate(**values)
        session.add(row)
        rows.append(row)
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return rows


async def list_pending_raw_candidates(
    session: AsyncSession,
    *,
    older_than_days: int = 3,
) -> list[RawCandidate]:
    await expire_raw_candidates(session, older_than_days=older_than_days)
    result = await session.execute(
        select(RawCandidate)
        .where(RawCandidate.status == "pending")
        .order_by(RawCandidate.id.asc())
    )
    return list(result.scalars().all())


async def mark_raw_candidates_consumed(session: AsyncSession, ids: Iterable[int]) -> None:
    id_list = [candidate_id for candidate_id in ids if candidate_id]
    if not id_list:
        return
    await session.execute(
        update(RawCandidate)
        .where(RawCandidate.id.in_(id_list))
        .values(status="consumed")
    )
    await session.commit()


async def expire_raw_candidates(session: AsyncSession, *, older_than_days: int = 3) -> int:
    cutoff = _utc_now() - timedelta(days=max(older_than_days, 1))
    result = await session.execute(
        update(RawCandidate)
        .where(RawCandidate.status == "pending")
        .where(RawCandidate.collected_at < cutoff)
        .values(status="expired")
    )
    await session.commit()
    return result.rowcount or 0
