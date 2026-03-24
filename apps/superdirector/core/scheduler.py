from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from compat import UTC

from db import crud
from db.models import ScheduleJob
from db.session import AsyncSessionLocal
from pipeline.pipeline import run_collect_only, run_pipeline
from pipeline.feedback_review import run_feedback_weekly_cycle
from pipeline.quality_gate import quality_gate
from integrations.telegram_sender import send_casey_message

_scheduler: AsyncIOScheduler | None = None
_app_state = None
_scheduler_tz = ZoneInfo("Asia/Shanghai")

DEFAULT_SCHEDULE_JOBS = (
    {
        "job_id": "collector_morning",
        "cron_hour": 8,
        "cron_minute": 0,
        "enabled": True,
        "description": "早间数据采集",
    },
    {
        "job_id": "collector_evening",
        "cron_hour": 18,
        "cron_minute": 0,
        "enabled": True,
        "description": "晚间数据采集",
    },
    {
        "job_id": "morning_briefing",
        "cron_hour": 8,
        "cron_minute": 30,
        "enabled": True,
        "description": "每日选题早报",
    },
    {
        "job_id": "feedback_weekly",
        "cron_hour": 22,
        "cron_minute": 0,
        "enabled": True,
        "description": "每周反馈复盘",
    },
)

_SOURCE_LABELS = {
    "wechat_rss": "微信公众号/RSS",
    "wewe_rss": "微信公众号/RSS",
    "baidu_search": "百度搜索",
    "nmpa_news": "国家药监局",
    "govcn_policy": "国务院/政府网",
    "who_alerts": "WHO 警报",
    "rss_fda_medwatch": "FDA MedWatch",
    "rss_nyt_health": "NYT Health",
    "rss_sciencedaily_health": "ScienceDaily Health",
    "rss_stat_backup": "STAT News",
    "rss_stats_release": "国家统计局",
    "rss_stats_interpretation": "国家统计局解读",
}

_FIT_LABELS = {
    "strong": "强",
    "medium": "中",
    "weak": "弱",
    "click": "会点开",
    "save": "会收藏",
    "ignore": "大概率略过",
    "forward": "会转发",
    "watch": "会看完",
}


def _utc_now_text() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _job_trigger(job: ScheduleJob) -> CronTrigger:
    kwargs = {"hour": job.cron_hour, "minute": job.cron_minute}
    if job.job_id == "feedback_weekly":
        kwargs["day_of_week"] = "sun"
    return CronTrigger(**kwargs)


def _short(text: str | None, max_len: int = 110) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _source_label(source: str | None) -> str:
    return _SOURCE_LABELS.get((source or "").strip(), source or "-")


def _fit_label(value: str | None) -> str:
    return _FIT_LABELS.get((value or "").strip(), value or "-")


async def _format_morning_briefing() -> tuple[str | None, str | None]:
    from core.config import TOP_N, today_str

    async with AsyncSessionLocal() as session:
        run = await crud.get_latest_briefing_run(session, date_str=today_str())
        if not run:
            return None, "今天还没有完成的选题结果，早报已跳过。"
        topics = await crud.get_output_topics_for_run(session, run.id, limit=TOP_N)
        gate_passed, gate_reason = quality_gate(topics, run.raw_item_count or 0)

    if not topics:
        return None, "今天还没有可展示的完成选题，早报已跳过。"
    if not gate_passed:
        return (
            "\n".join(
                [
                    "⚠️ 今日选题未通过质量检查",
                    f"原因: {gate_reason}",
                    "建议: /sd run 手动重跑，或 /sd status 检查信源状态",
                ]
            ),
            None,
        )

    lines = [
        "━━━━━━━━━━━━━━━━━━━━",
        f"SuperDirector 早报 | {today_str()} | Top {len(topics)}",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for idx, topic in enumerate(topics, start=1):
        lines.append("────────────────────")
        lines.append(f"【{idx:02d}】{topic.title}")
        lines.append(
            f"定位：{topic.topic_line_primary or '-'}｜{topic.content_role or '-'}｜{topic.platform_priority or '-'}"
        )
        lines.append(
            f"受众：添爸 {_fit_label(topic.creator_fit)}｜李姐 {_fit_label(topic.li_jie_value)}｜张阿姨 {_fit_label(topic.zhang_auntie_value)}"
        )
        lines.append(f"来源：{_source_label(topic.source)}｜时效：{topic.timestamp or topic.date or '-'}")
        lines.append(f"评分：{topic.score_total}")
        if topic.summary:
            lines.append(f"选题简介：{_short(topic.summary, 120)}")
        if topic.raw_snippet:
            lines.append(f"硬核事实/数据：{_short(topic.raw_snippet, 120)}")
        if getattr(topic, "frame_status", "") == "rejected":
            lines.append(
                f"⚠️ 框架未通过质量检查：{getattr(topic, 'frame_rejection_reason', '') or '未说明原因'}"
            )
        if topic.url:
            lines.append(f"出处链接：{topic.url}")
        lines.append("")
    lines.append("可继续回复：给第1条出个视频号框架 / 最近一周高分选题给我推5条")
    return "\n".join(lines).strip(), None


async def _run_job(job_id: str) -> dict:
    if _app_state is None:
        raise RuntimeError("Scheduler app state is not initialized")

    if job_id in {"collector_morning", "collector_evening"}:
        if job_id == "collector_evening":
            result = await run_collect_only(_app_state)
        else:
            result = await run_pipeline(_app_state)
        status = "ok" if result.get("run_id") else "failed"
        return {"status": status, "result": result}

    if job_id == "morning_briefing":
        text, skip_reason = await _format_morning_briefing()
        if skip_reason:
            return {"status": "skipped", "result": {"message": skip_reason}}
        try:
            await send_casey_message(_app_state.ext_client, text)
        except Exception:
            await asyncio.sleep(60)
            await send_casey_message(_app_state.ext_client, text)
        return {"status": "ok", "result": {"message": "Morning briefing sent"}}

    if job_id == "feedback_weekly":
        result = await run_feedback_weekly_cycle(_app_state.ext_client)
        return {"status": str(result.get("status") or "ok"), "result": result}

    raise RuntimeError(f"Unsupported schedule job: {job_id}")


async def _execute_and_record(job_id: str) -> dict:
    error_message: str | None = None
    status = "ok"
    result: dict | None = None
    try:
        result = await _run_job(job_id)
        status = str(result.get("status") or "ok")
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error_message = str(exc)
        result = {"error": error_message}

    async with AsyncSessionLocal() as session:
        await crud.update_schedule_job_run(
            session,
            job_id,
            status=status,
            error=error_message,
        )
    return {"job_id": job_id, "status": status, "result": result, "ran_at": _utc_now_text()}


def _ensure_job_registered(job: ScheduleJob) -> None:
    if _scheduler is None:
        return
    if not job.enabled:
        if _scheduler.get_job(job.job_id):
            _scheduler.remove_job(job.job_id)
        return

    trigger = _job_trigger(job)
    if _scheduler.get_job(job.job_id):
        _scheduler.reschedule_job(job.job_id, trigger=trigger)
    else:
        _scheduler.add_job(_execute_and_record, trigger=trigger, id=job.job_id, args=[job.job_id])


async def refresh_schedule_job(job_id: str) -> ScheduleJob | None:
    async with AsyncSessionLocal() as session:
        job = await crud.get_schedule_job(session, job_id)
    if job:
        _ensure_job_registered(job)
    elif _scheduler and _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
    return job


async def start_scheduler(app_state):
    global _scheduler, _app_state
    _app_state = app_state
    if _scheduler:
        return _scheduler

    async with AsyncSessionLocal() as session:
        await crud.ensure_schedule_jobs(session, DEFAULT_SCHEDULE_JOBS)
        jobs = await crud.list_schedule_jobs(session)

    scheduler = AsyncIOScheduler(timezone=_scheduler_tz)
    _scheduler = scheduler
    for job in jobs:
        _ensure_job_registered(job)
    scheduler.start()
    return scheduler


def stop_scheduler():
    global _scheduler, _app_state
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    _app_state = None


async def list_schedule_jobs() -> list[ScheduleJob]:
    async with AsyncSessionLocal() as session:
        return await crud.list_schedule_jobs(session)


async def run_schedule_job_now(job_id: str) -> dict:
    return await _execute_and_record(job_id)
