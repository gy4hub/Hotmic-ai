import asyncio
from typing import Any

from compat import asyncio_timeout

from app_logging import get_logger
from config import (
    EDITORIAL_PERFORMANCE_LOOKBACK_DAYS,
    EDITORIAL_RECENT_WINDOW_DAYS,
    TOP_N,
    FRAME_TOP_N,
    PREFILTER_ENABLED,
    GEMINI_FLASH_MODEL,
    QWEN_API_KEY,
    QWEN_MODEL,
    today_str,
    PIPELINE_RUN_STALE_SECONDS,
    PIPELINE_STEP_TIMEOUT_SECONDS,
)
from pipeline.collector import collect_fresh_topics, collect_topics
from pipeline.analyzer import analyze_topics, prefilter_topics
from pipeline.scorer import score_topics
from pipeline.editorial import select_topics_for_output
from pipeline.frame_gate import frame_quality_gate
from pipeline.framer import generate_frames
from pipeline.quality_gate import quality_gate
from pipeline.pricing import estimate_cost_usd
from tools.bitable_writer import sync_topics_to_bitable
from db.session import AsyncSessionLocal
from db import crud
from pipeline.types import EditorialMeta, ScoreDetailPayload, TopicPayload, UsageSummary

logger = get_logger(__name__)

_NON_FATAL_COLLECTOR_PREFIXES = (
    "RSS fetch failed",
    "Official source fetch failed",
    "Brave fetch failed",
    "BRAVE_SEARCH_API_KEY missing",
    "Baidu fetch failed",
    "BAIDU_API_KEY missing",
)


def _extract_tokens(usage: UsageSummary) -> tuple[int | None, int | None]:
    if not usage:
        return None, None
    return usage.get("input_tokens"), usage.get("output_tokens")


def _is_non_fatal_collector_issue(error: Any) -> bool:
    text = str(error)
    return any(text.startswith(prefix) for prefix in _NON_FATAL_COLLECTOR_PREFIXES)


async def _log_usage(session, usage: UsageSummary) -> tuple[int, int, float]:
    prompt_tokens, output_tokens = _extract_tokens(usage)
    if prompt_tokens is None and output_tokens is None:
        return 0, 0, 0.0
    cost = estimate_cost_usd(
        usage.get("provider"),
        usage.get("model"),
        prompt_tokens,
        output_tokens,
    )
    await crud.log_cost(
        session,
        provider=usage.get("provider") or "unknown",
        model=usage.get("model") or GEMINI_FLASH_MODEL,
        endpoint=usage.get("endpoint") or "unknown",
        input_tokens=prompt_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )
    return prompt_tokens or 0, output_tokens or 0, cost or 0.0


def _compute_run_status(topics: list[TopicPayload], errors: list[str]) -> str:
    fatal_errors = [e for e in errors if not _is_non_fatal_collector_issue(e)]
    if fatal_errors:
        return "partial"
    if len(topics) < TOP_N:
        return "partial"
    if any((t.get("errors") or []) or t.get("status") == "failed" for t in topics):
        return "partial"
    return "ok"


def _apply_frame_quality_gate(topics: list[TopicPayload]) -> list[TopicPayload]:
    gated: list[TopicPayload] = []
    for topic in topics:
        if topic.get("frame_status") == "skipped":
            gated.append(topic)
            continue
        if topic.get("frame_status") == "rejected" and topic.get("frame_rejection_reason"):
            gated.append(topic)
            continue
        passed, reason = frame_quality_gate(topic)
        gated.append(
            {
                **topic,
                "frame_status": "passed" if passed else "rejected",
                "frame_rejection_reason": None if passed else reason,
            }
        )
    return gated


async def _run_step(label: str, coro, *, timeout_seconds: int):
    try:
        async with asyncio_timeout(timeout_seconds):
            return await coro
    except TimeoutError as exc:
        raise RuntimeError(f"{label} timed out after {timeout_seconds}s") from exc


def _split_topics_for_framing(topics: list[TopicPayload]) -> tuple[list[TopicPayload], list[TopicPayload]]:
    frame_limit = max(0, min(FRAME_TOP_N, len(topics)))
    frame_candidates = topics[:frame_limit]
    skipped = [
        {
            **topic,
            "frame_status": "skipped",
            "frame_rejection_reason": "skipped_by_frame_limit",
            "frame_tier": None,
        }
        for topic in topics[frame_limit:]
    ]
    return frame_candidates, skipped


async def run_pipeline(app_state) -> dict[str, Any]:
    errors: list[str] = []

    async with AsyncSessionLocal() as session:
        await crud.fail_stale_pipeline_runs(
            session,
            stale_after_seconds=PIPELINE_RUN_STALE_SECONDS,
        )
        run = await crud.create_pipeline_run(session)
    date_str = today_str()
    output_topics: list[TopicPayload] = []
    score_details: list[ScoreDetailPayload] = []
    usage_prefilter: UsageSummary = {}
    usage_a: UsageSummary = {}
    usage_f: UsageSummary = {}
    raw_item_count = 0
    gate_passed = True
    gate_reason = "通过"
    pending_candidate_ids: list[int] = []
    editorial_meta: EditorialMeta = {}

    try:
        async with AsyncSessionLocal() as session:
            pending_rows = await crud.list_pending_raw_candidates(session)
        pending_items = [
            {
                "title": row.title,
                "url": row.url,
                "source": row.source,
                "timestamp": row.published_at,
                "raw_snippet": row.snippet,
                "fingerprint": row.fingerprint,
            }
            for row in pending_rows
        ]
        pending_candidate_ids = [row.id for row in pending_rows]
        collected, collect_errors = await _run_step(
            "Collector",
            collect_topics(
                app_state.int_client,
                app_state.ext_client,
                pending_items=pending_items,
            ),
            timeout_seconds=PIPELINE_STEP_TIMEOUT_SECONDS,
        )
        raw_item_count = len(collected)
        errors.extend(collect_errors)
        analysis_input = collected
        if PREFILTER_ENABLED:
            analysis_input, prefilter_errors, usage_prefilter = await _run_step(
                "Prefilter",
                prefilter_topics(app_state.int_client, collected),
                timeout_seconds=PIPELINE_STEP_TIMEOUT_SECONDS,
            )
            errors.extend(prefilter_errors)

        analyzed, analyze_errors, usage_a = await _run_step(
            "Analyzer",
            analyze_topics(app_state.ext_client, app_state.int_client, analysis_input),
            timeout_seconds=PIPELINE_STEP_TIMEOUT_SECONDS,
        )
        errors.extend(analyze_errors)

        scored, score_details = score_topics(analyzed)
        async with AsyncSessionLocal() as session:
            recent_rows = await crud.get_recent_editorial_topics(
                session,
                since_days=max(EDITORIAL_RECENT_WINDOW_DAYS, EDITORIAL_PERFORMANCE_LOOKBACK_DAYS),
                limit=200,
            )
        recent_topics = [
            {
                "topic_line_primary": row.topic_line_primary,
                "content_role": row.content_role,
                "topic_cluster": row.topic_cluster,
                "source": row.source,
                "publish_status": row.publish_status,
                "publish_at": row.publish_at,
                "publish_url": row.publish_url,
                "perf_watch_rate": row.perf_watch_rate,
            }
            for row in recent_rows
        ]
        top_scored, editorial_meta = select_topics_for_output(scored, recent_topics, top_n=TOP_N)
        gate_passed, gate_reason = quality_gate(top_scored, raw_item_count)

        frame_candidates, skipped_topics = _split_topics_for_framing(top_scored)
        framed_topics: list[TopicPayload] = []
        frame_errors: list[str] = []
        if frame_candidates:
            framed_topics, frame_errors, usage_f = await _run_step(
                "Framer",
                generate_frames(app_state.ext_client, app_state.int_client, frame_candidates),
                timeout_seconds=PIPELINE_STEP_TIMEOUT_SECONDS,
            )
            errors.extend(frame_errors)
            framed_topics = _apply_frame_quality_gate(framed_topics)

        output_topics = framed_topics + skipped_topics

        for t in output_topics:
            t["date"] = date_str
            t["pipeline_run_id"] = run.id
            t["model_version"] = QWEN_MODEL if QWEN_API_KEY else GEMINI_FLASH_MODEL
            if "errors" not in t:
                t["errors"] = []

        async with AsyncSessionLocal() as session:
            rows = await crud.insert_topics(session, output_topics)
            id_map = {r.topic_id: r.id for r in rows}

            filtered_details = []
            for d in score_details:
                topic_key = d.get("topic_id")
                if not topic_key:
                    continue
                db_id = id_map.get(topic_key)
                if not db_id:
                    continue
                filtered_details.append({**d, "topic_id": db_id})

            if filtered_details:
                await crud.insert_score_details(session, filtered_details)

            total_prompt_tokens = 0
            total_output_tokens = 0
            total_cost_usd = 0.0

            for usage_item in (usage_prefilter, usage_a, usage_f):
                prompt_tokens, output_tokens, cost = await _log_usage(session, usage_item)
                total_prompt_tokens += prompt_tokens
                total_output_tokens += output_tokens
                total_cost_usd += cost

            bitable_result = await _run_step(
                "Bitable sync",
                sync_topics_to_bitable(app_state.ext_client, output_topics),
                timeout_seconds=PIPELINE_STEP_TIMEOUT_SECONDS,
            )
            if bitable_result.get("queued_tasks"):
                await crud.enqueue_bitable_sync_tasks(session, bitable_result["queued_tasks"])
            errors.extend(bitable_result.get("errors") or [])
            if bitable_result.get("errors"):
                logger.warning("Bitable sync degraded to SQLite outbox: %s", bitable_result)
                await crud.log_system(
                    session,
                    level="warning",
                    module="bitable",
                    message="Bitable sync degraded to SQLite outbox",
                    details=bitable_result,
                )

            if pending_candidate_ids:
                await crud.mark_raw_candidates_consumed(session, pending_candidate_ids)

            run_status = "quality_gate_failed" if not gate_passed else _compute_run_status(output_topics, errors)
            if not gate_passed:
                errors.append(gate_reason)
            await crud.finalize_pipeline_run(
                session,
                run_id=run.id,
                status=run_status,
                topics_count=len(output_topics),
                raw_item_count=raw_item_count,
                error_count=len(errors),
                total_tokens=total_prompt_tokens + total_output_tokens
                if (total_prompt_tokens or total_output_tokens)
                else None,
                total_cost=round(total_cost_usd, 6) if total_cost_usd else None,
                errors=errors,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline run failed: %s", exc)
        errors.append(str(exc))
        async with AsyncSessionLocal() as session:
            await crud.finalize_pipeline_run(
                session,
                run_id=run.id,
                status="failed",
                topics_count=len(output_topics),
                raw_item_count=raw_item_count,
                error_count=len(errors),
                total_tokens=None,
                total_cost=None,
                errors=errors,
            )

    response = {
        "run_id": run.id,
        "date": date_str,
        "raw_item_count": raw_item_count,
        "quality_gate": {"passed": gate_passed, "reason": gate_reason},
        "editorial": editorial_meta,
        "topics": output_topics,
        "errors": errors,
    }
    return response


async def run_collect_only(app_state) -> dict[str, Any]:
    errors: list[str] = []
    raw_item_count = 0
    async with AsyncSessionLocal() as session:
        await crud.fail_stale_pipeline_runs(
            session,
            stale_after_seconds=PIPELINE_RUN_STALE_SECONDS,
        )
        run = await crud.create_pipeline_run(session)

    try:
        collected, collect_errors = await _run_step(
            "Collector",
            collect_fresh_topics(app_state.int_client, app_state.ext_client),
            timeout_seconds=PIPELINE_STEP_TIMEOUT_SECONDS,
        )
        raw_item_count = len(collected)
        errors.extend(collect_errors)
        async with AsyncSessionLocal() as session:
            await crud.insert_raw_candidates(session, run_id=run.id, items=collected)
            await crud.finalize_pipeline_run(
                session,
                run_id=run.id,
                status="collected",
                topics_count=0,
                raw_item_count=raw_item_count,
                error_count=len(errors),
                total_tokens=None,
                total_cost=None,
                errors=errors,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Collect-only run failed: %s", exc)
        errors.append(str(exc))
        async with AsyncSessionLocal() as session:
            await crud.finalize_pipeline_run(
                session,
                run_id=run.id,
                status="failed",
                topics_count=0,
                raw_item_count=raw_item_count,
                error_count=len(errors),
                total_tokens=None,
                total_cost=None,
                errors=errors,
            )

    return {
        "run_id": run.id,
        "date": today_str(),
        "raw_item_count": raw_item_count,
        "topics": [],
        "errors": errors,
    }
