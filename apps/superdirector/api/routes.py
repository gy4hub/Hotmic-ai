from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, func, desc
import asyncio
from datetime import UTC, date, datetime
from html import escape
import json
import re
from pathlib import Path
from db.session import AsyncSessionLocal
from db.models import PipelineRun, Topic, ApiCostLog
from pipeline.collector import (
    BRAVE_ENDPOINT,
    BRAVE_QUERY_SPECS,
    OFFICIAL_API_SOURCES,
    OFFICIAL_HTML_SOURCES,
    OFFICIAL_PAGE_HEADERS,
    RSS_DISCOVERY_BASKET_SOURCES,
    RSS_SOURCES,
    MEDIA_CRAWLER_SOURCE_SPECS,
    _latest_mediacrawler_file,
    _parse_fda_enforcement,
    _parse_html_listing,
    _parse_rss,
    TAVILY_ENDPOINT,
)
from pipeline.pipeline import run_pipeline
from pipeline.analyzer import analyze_topics
from pipeline.scorer import SOURCE_BUCKETS, explain_scores, get_scoring_config, score_topics
from pipeline.editorial import editorial_config_summary
from pipeline.backtest import run_editorial_backtest
from pipeline.framer import generate_frames
from pipeline.feedback import sync_feedback_from_bitable, feedback_sync_enabled
from pipeline.feedback_collector import (
    _upsert_bitable_feedback,
    collect_douyin_feedback,
    collect_xhs_feedback,
    douyin_cookie_exists,
    feedback_status_summary,
    save_douyin_cookie,
)
from pipeline.review_patch import apply_review_patch
from pipeline.scoring_tuner import apply_scoring_patch, interpret_scoring_instruction
from pipeline.scoring_config import (
    create_scoring_preview,
    create_scoring_snapshot,
    list_scoring_history,
    load_scoring_preview,
    restore_scoring_snapshot,
)
from integrations.wewe_monitor import (
    add_wewe_account,
    await_wewe_login_and_add,
    build_wewe_qr_png,
    build_wewe_scan_url,
    create_wewe_login_qr,
    get_wewe_health,
    get_wewe_login_result,
)
from integrations.telegram_sender import send_casey_message
from core.config import (
    today_str,
    TOP_N,
    BAIDU_API_KEY,
    BRAVE_SEARCH_API_KEYS,
    TAVILY_API_KEY,
    TAVILY_ENABLED,
    QWEN_API_KEY,
    QWEN_MODEL,
    GEMINI_FLASH_MODEL,
    BRAVE_RESULT_COUNT,
    CASEY_PROFILE_PATH,
    TAVILY_RESULT_COUNT,
    HOTMIC_SCRIPT_CREATOR_DIR,
    HOTMIC_STYLE_CONFIDENCE_THRESHOLD,
    HOTMIC_STYLE_DB_PATH,
    MEDIA_CRAWLER_MAX_AGE_HOURS,
    is_mock_mode,
    load_casey_profile,
)
from db import crud
from core.scheduler import list_schedule_jobs, refresh_schedule_job, run_schedule_job_now

router = APIRouter()
_NON_FATAL_COLLECTOR_PREFIXES = (
    "RSS fetch failed",
    "Official source fetch failed",
    "Brave fetch failed",
    "BRAVE_SEARCH_API_KEY missing",
    "Baidu fetch failed",
    "BAIDU_API_KEY missing",
    "Tavily fetch failed",
    "TAVILY_API_KEY missing",
)
SOURCE_HEALTH_INT_TIMEOUT = 5
SOURCE_HEALTH_EXT_TIMEOUT = 8
SOURCE_HEALTH_TASK_TIMEOUT = 9


async def _watch_wewe_login_and_notify(app_state, uuid: str, baseline_health: dict | None = None) -> None:
    try:
        result = await await_wewe_login_and_add(
            app_state.int_client,
            uuid,
            timeout_seconds=90,
            poll_interval=3,
        )
        if result.get("authenticated") and ((result.get("account_add") or {}).get("added") is True):
            health = result.get("health") or {}
            baseline_items = (baseline_health or {}).get("items") or []
            baseline_ids = {
                str(item.get("id") or "").strip()
                for item in baseline_items
                if str(item.get("id") or "").strip()
            }
            account_id = str(result.get("account_id") or "").strip()
            account_name = str(result.get("account_name") or "").strip()
            enabled_count = health.get("account_enabled")
            total_count = health.get("account_total")
            if account_id and account_id not in baseline_ids:
                lines = [
                    "Casey 汇报：WeWe-RSS 新账号已添加成功。",
                    f"uuid: {uuid}",
                    f"账号：{account_name or account_id} ({account_id})",
                ]
            else:
                lines = [
                    "Casey 汇报：WeWe-RSS 登录已确认，但这次没有新增账号。",
                    f"uuid: {uuid}",
                ]
                if account_id:
                    lines.append(f"账号：{account_name or account_id} ({account_id})")
            if enabled_count is not None and total_count is not None:
                lines.append(f"当前可用账号：{enabled_count}/{total_count}")
            text = "\n".join(lines)
        else:
            login_result = result.get("login_result") or {}
            detail = ""
            if isinstance(login_result, dict):
                detail = str(login_result.get("message") or "").strip()
            if not detail:
                detail = str(result.get("message") or "").strip()
            health = result.get("health") or {}
            if not detail and isinstance(health, dict):
                detail = str(health.get("message") or "").strip()
            if result.get("timeout"):
                detail = detail or "等待扫码确认超时。"
            text = "\n".join(
                [
                    "Casey 提醒：WeWe-RSS 这次扫码还没有完成登录。",
                    f"uuid: {uuid}",
                    detail or "如果二维码已过期，请重新发送 `/sd wewe-login`。",
                ]
            )
        await send_casey_message(app_state.ext_client, text)
    except Exception as exc:  # noqa: BLE001
        await send_casey_message(
            app_state.ext_client,
            "\n".join(
                [
                    "Casey 提醒：WeWe-RSS 登录结果检查失败。",
                    f"uuid: {uuid}",
                    str(exc),
                ]
            ),
        )
    finally:
        tasks = getattr(app_state, "wewe_login_watch_tasks", None)
        if isinstance(tasks, dict):
            tasks.pop(uuid, None)


def _json_loads(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except Exception:
        return value


def _is_non_fatal_collector_issue(error) -> bool:
    text = str(error)
    return any(text.startswith(prefix) for prefix in _NON_FATAL_COLLECTOR_PREFIXES)


def _module_status_from_errors(
    *,
    errors: list,
    prefix: str,
    total_sources: int,
    has_selected_topics: bool,
    missing_key: bool = False,
) -> str:
    if missing_key:
        return "missing_key"
    failure_count = sum(1 for error in errors if str(error).startswith(prefix))
    if has_selected_topics:
        return "ok"
    if total_sources <= 0:
        return "ok"
    return "error" if failure_count >= total_sources else "ok"


def _display_run_status(run: PipelineRun, errors: list) -> str:
    if run.status != "partial":
        return run.status
    if run.topics_count and run.topics_count >= TOP_N and all(
        _is_non_fatal_collector_issue(error) for error in errors
    ):
        return "ok"
    return run.status


def _source_ok(message: str, **extra):
    return {"status": "ok", "message": message, **extra}


def _source_warning(message: str, **extra):
    return {"status": "warning", "message": message, **extra}


def _source_error(message: str, **extra):
    return {"status": "error", "message": message, **extra}


def _source_missing_key(message: str, **extra):
    return {"status": "missing_key", "message": message, **extra}


def _exc_text(exc: Exception) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _serialize_schedule_job(job) -> dict:
    return {
        "job_id": job.job_id,
        "hour": job.cron_hour,
        "minute": job.cron_minute,
        "enabled": bool(job.enabled),
        "description": job.description,
        "last_run_at": job.last_run_at,
        "last_run_status": job.last_run_status,
        "last_run_error": job.last_run_error,
        "updated_at": job.updated_at,
    }


def _serialize_topic(row) -> dict:
    return {
        "id": row.id,
        "topic_id": row.topic_id,
        "date": row.date,
        "title": row.title,
        "score_total": row.score_total,
        "quality_score": row.score_total,
        "editorial_priority_score": row.editorial_priority_score,
        "platform_priority": row.platform_priority,
        "summary": row.summary,
        "source": row.source,
        "timestamp": row.timestamp,
        "raw_snippet": row.raw_snippet,
        "keywords": row.keywords,
        "url": row.url,
        "topic_line_primary": row.topic_line_primary,
        "topic_line_secondary": row.topic_line_secondary,
        "line_confidence": row.line_confidence,
        "content_role": row.content_role,
        "creator_fit": row.creator_fit,
        "li_jie_value": row.li_jie_value,
        "zhang_auntie_value": row.zhang_auntie_value,
        "audience_core": row.audience_core,
        "compliance_risk": row.compliance_risk,
        "actionability_risk": row.actionability_risk,
        "topic_cluster": row.topic_cluster,
        "reject_type": row.reject_type,
        "rejection_reason": row.rejection_reason,
        "timeliness_window": row.timeliness_window,
        "platform_fit": row.platform_fit,
        "decision_impact_level": row.decision_impact_level,
        "selection_rank_reason": row.selection_rank_reason,
        "publish_status": getattr(row, "publish_status", None),
        "publish_url": getattr(row, "publish_url", None),
        "publish_at": getattr(row, "publish_at", None),
        "frame_status": getattr(row, "frame_status", None),
        "frame_rejection_reason": getattr(row, "frame_rejection_reason", None),
        "status": row.status,
        "errors": _json_loads(row.errors_json),
    }


def _json_list(value) -> list:
    parsed = _json_loads(value)
    if isinstance(parsed, list):
        return parsed
    if parsed in (None, ""):
        return []
    return [parsed]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        candidate = str(value or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def _sd_platform_to_hotmic(platform: str | None) -> str:
    normalized = str(platform or "").strip().lower()
    if normalized in {"wechat_video", "shipinhao"}:
        return "wechat_video"
    if normalized in {"douyin", "xiaohongshu"}:
        return normalized
    return "douyin"


def _hotmic_platform_to_sd(platform: str | None) -> str:
    normalized = str(platform or "").strip().lower()
    if normalized in {"wechat_video", "shipinhao"}:
        return "shipinhao"
    if normalized in {"douyin", "xiaohongshu"}:
        return normalized
    return "douyin"


def _source_bucket(source: str | None) -> str:
    if not source:
        return "other"
    if source in SOURCE_BUCKETS:
        return SOURCE_BUCKETS[source]
    if source.startswith("brave_"):
        return "search"
    return "other"


def _source_grade(source: str | None) -> str:
    bucket = _source_bucket(source)
    if bucket in {"official", "trusted_rss"}:
        return "A"
    if bucket in {"industry_media", "platform_native"}:
        return "B"
    return "C"


def _extract_source_urls(row) -> list[str]:
    urls: list[str] = []
    if row.url:
        urls.append(str(row.url))

    for item in _json_list(row.search_sources):
        if isinstance(item, dict):
            candidate = item.get("url") or item.get("link")
        else:
            candidate = item
        candidate_text = str(candidate or "").strip()
        if candidate_text.startswith("http://") or candidate_text.startswith("https://"):
            urls.append(candidate_text)

    return _dedupe_strings(urls)


def _extract_verified_facts(row) -> list[str]:
    facts: list[str] = []
    for text in (row.summary, row.raw_snippet, row.title):
        if not text:
            continue
        for chunk in re.split(r"[。！？；;\n]+", str(text)):
            candidate = chunk.strip(" -")
            if len(candidate) < 8:
                continue
            facts.append(candidate)
            if len(_dedupe_strings(facts)) >= 5:
                return _dedupe_strings(facts)[:5]
    return _dedupe_strings(facts)[:5]


def _frame_payload(frame_json: str | None) -> dict:
    frame = _json_loads(frame_json)
    if not isinstance(frame, dict):
        frame = {}
    outline = frame.get("outline") or []
    if not isinstance(outline, list):
        outline = [outline]
    return {
        "hook": frame.get("hook"),
        "outline": [str(item) for item in outline if str(item or "").strip()],
        "cta": frame.get("cta"),
    }


def _load_high_confidence_style_rules(
    db_path: str | None = None,
    threshold: float | None = None,
) -> list[dict]:
    path = Path(db_path or HOTMIC_STYLE_DB_PATH)
    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    rules = db.get("rules") or []
    if not isinstance(rules, list):
        return []
    minimum = HOTMIC_STYLE_CONFIDENCE_THRESHOLD if threshold is None else threshold
    filtered = [
        rule for rule in rules
        if isinstance(rule, dict)
        and float(rule.get("confidence") or 0) >= minimum
        and rule.get("status", "candidate") != "deleted"
    ]
    filtered.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
    return filtered


def _build_hotmic_script_payload(row, *, platform_override: str | None = None) -> dict:
    content_role = str(row.content_role or "").strip().lower()
    keywords = [str(item) for item in _json_list(row.keywords)]
    return {
        "topic": {
            "topic_id": row.topic_id,
            "title": row.title,
            "summary": row.summary,
            "keywords": keywords,
            "source": row.source,
            "source_urls": _extract_source_urls(row),
        },
        "content_type": "spread" if content_role == "spread" else "collect",
        "platform_priority": _sd_platform_to_hotmic(platform_override or row.platform_priority),
        "frame": _frame_payload(row.frame_json),
        "persona_profile": load_casey_profile(),
        "style_patch": _load_high_confidence_style_rules(),
        "compliance_context": {
            "source_grade": _source_grade(row.source),
            "verified_facts": _extract_verified_facts(row),
            "compliance_risk": row.compliance_risk,
            "actionability_risk": row.actionability_risk,
        },
    }


def _build_hotmic_launch_command() -> str | None:
    script_dir = Path(HOTMIC_SCRIPT_CREATOR_DIR)
    if not script_dir.exists():
        return None
    return (
        f"cd {script_dir} && "
        f"python scripts/load_style_rules.py --db {HOTMIC_STYLE_DB_PATH} "
        f"--profile {CASEY_PROFILE_PATH} --profile-summary --summary"
    )


async def _get_today_ranked_topics(*, limit: int | None = None) -> tuple[PipelineRun | None, list[Topic]]:
    async with AsyncSessionLocal() as session:
        run = await crud.get_latest_completed_run(session, date_str=today_str())
        if not run:
            return None, []
        rows = await crud.get_output_topics_for_run(session, run.id, limit=limit or TOP_N)
    return run, rows


async def _resolve_today_ranked_topic(rank: int) -> tuple[PipelineRun, Topic]:
    if rank < 1:
        raise HTTPException(status_code=400, detail="rank must be >= 1")

    run, rows = await _get_today_ranked_topics(limit=max(rank, TOP_N))
    if not run or not rows:
        raise HTTPException(status_code=404, detail="No ranked topics available for today")
    if rank > len(rows):
        raise HTTPException(
            status_code=404,
            detail=f"Today's ranked topics only have {len(rows)} items; rank {rank} is unavailable",
        )
    return run, rows[rank - 1]


def _telegram_script_message(*, rank: int, row, hotmic_input: dict, launch_command: str | None) -> str:
    pretty_json = json.dumps(hotmic_input, ensure_ascii=False, indent=2)
    parts = [
        f"Casey 汇报：已生成今日第 {rank} 条的 HotMic 创作输入。",
        f"标题：{escape(str(row.title or '-'))}",
        f"topic_id：<code>{escape(str(row.topic_id or '-'))}</code>",
        f"平台：{escape(str(hotmic_input.get('platform_priority') or '-'))}",
        f"类型：{escape(str(hotmic_input.get('content_type') or '-'))}",
        "创作输入：",
        f"<pre>{escape(pretty_json)}</pre>",
    ]
    if launch_command:
        parts.extend(
            [
                "启动命令：",
                f"<pre>{escape(launch_command)}</pre>",
            ]
        )
    return "\n".join(parts)


def _value_from_row(row, key: str):
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _telegram_publish_message(*, rank: int, row, script_path: str | None) -> str:
    parts = [
        f"Casey 汇报：已确认今日第 {rank} 条发布完成。",
        f"标题：{escape(str(_value_from_row(row, 'title') or '-'))}",
        f"平台：{escape(str(_value_from_row(row, 'platform_priority') or '-'))}",
        f"链接：{escape(str(_value_from_row(row, 'publish_url') or '-'))}",
        f"时间：{escape(str(_value_from_row(row, 'publish_at') or '-'))}",
    ]
    if script_path:
        parts.append(f"脚本：<code>{escape(script_path)}</code>")
    return "\n".join(parts)


async def _confirm_publish_for_topic(
    *,
    topic_id: str,
    payload: dict,
    ext_client,
) -> dict:
    publish_url = str(payload.get("publish_url") or "").strip()
    if not publish_url:
        raise HTTPException(status_code=400, detail="publish_url is required")

    platform = str(payload.get("platform") or "").strip() or None
    publish_at = str(payload.get("publish_at") or "").strip() or (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    script_path = str(payload.get("script_path") or "").strip() or None

    async with AsyncSessionLocal() as session:
        row = await crud.get_topic_by_topic_id(session, topic_id)
        if not row:
            raise HTTPException(status_code=404, detail="Topic not found")

        creator_ops = _json_loads(row.creator_ops) if row.creator_ops else {}
        if not isinstance(creator_ops, dict):
            creator_ops = {"raw": row.creator_ops}
        creator_ops["last_publish"] = {
            "platform": _sd_platform_to_hotmic(platform or row.platform_priority),
            "publish_url": publish_url,
            "publish_at": publish_at,
            "script_path": script_path,
        }

        updated_row = await crud.update_topic_feedback(
            session,
            topic_id,
            {
                "publish_status": "published",
                "publish_url": publish_url,
                "publish_at": publish_at,
                "platform_priority": _hotmic_platform_to_sd(platform or row.platform_priority),
                "creator_ops": json.dumps(creator_ops, ensure_ascii=False),
            },
        )

    bitable_result = await _upsert_bitable_feedback(
        ext_client,
        [
            {
                "topic_id": topic_id,
                "publish_status": "published",
                "publish_url": publish_url,
                "publish_at": publish_at,
            }
        ],
    )

    return {
        "topic": _serialize_topic(updated_row),
        "script_path": script_path,
        "bitable_sync": bitable_result,
    }


def _parse_optional_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise HTTPException(status_code=400, detail="enabled must be a boolean")


async def _guard_source_check(label: str, coro):
    try:
        return await asyncio.wait_for(coro, timeout=SOURCE_HEALTH_TASK_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        return _source_error(f"{label} 检查失败: {_exc_text(exc)}")


async def _check_rss_source(int_client, spec: dict) -> dict:
    try:
        resp = await int_client.request("GET", spec["url"], timeout=SOURCE_HEALTH_INT_TIMEOUT)
        resp.raise_for_status()
        items = _parse_rss(resp.text, spec["source"], limit=1)
        if items:
            return _source_ok("RSS 可访问且能解析到内容。", item_count=len(items), url=spec["url"])
        return _source_warning("RSS 可访问，但当前未解析到内容。", item_count=0, url=spec["url"])
    except Exception as exc:  # noqa: BLE001
        return _source_error(f"RSS 检查失败: {_exc_text(exc)}", url=spec["url"])


async def _check_brave_source(ext_client) -> dict:
    if not BRAVE_SEARCH_API_KEYS:
        return _source_missing_key("BRAVE_SEARCH_API_KEY 未配置。")
    spec = BRAVE_QUERY_SPECS[0]
    exhausted_count = 0
    last_error = ""
    for index, key in enumerate(BRAVE_SEARCH_API_KEYS, start=1):
        try:
            resp = await ext_client.request(
                "GET",
                BRAVE_ENDPOINT,
                params={
                    "q": spec["query"],
                    "count": 1,
                    "search_lang": "zh-hans",
                    "country": "cn",
                    "freshness": spec["freshness"],
                },
                headers={"X-Subscription-Token": key},
                timeout=SOURCE_HEALTH_EXT_TIMEOUT,
            )
            if resp.status_code == 402:
                exhausted_count += 1
                last_error = "402 Payment Required"
                continue
            resp.raise_for_status()
            results = resp.json().get("web", {}).get("results", [])[: max(1, BRAVE_RESULT_COUNT)]
            ok_message = "Brave 搜索可用。"
            warning_message = "Brave 可访问，但当前测试查询无结果。"
            if index > 1:
                ok_message = f"Brave 搜索可用，已自动切换到第 {index} 个 key。"
                warning_message = f"Brave 已自动切换到第 {index} 个 key，但当前测试查询无结果。"
            if results:
                return _source_ok(ok_message, sample_query=spec["query"], result_count=len(results))
            return _source_warning(warning_message, sample_query=spec["query"], result_count=0)
        except Exception as exc:  # noqa: BLE001
            text = _exc_text(exc)
            last_error = text
            if "402" in text:
                exhausted_count += 1
                continue
            return _source_error(f"Brave 检查失败: {text}", sample_query=spec["query"])
    if exhausted_count == len(BRAVE_SEARCH_API_KEYS):
        return _source_warning(
            "Brave 所有已配置 key 本月额度均已用尽，系统会继续使用百度和 RSS 补位。",
            sample_query=spec["query"],
        )
    return _source_error(f"Brave 检查失败: {last_error}", sample_query=spec["query"])


async def _check_baidu_source(int_client) -> dict:
    if not BAIDU_API_KEY:
        return _source_missing_key("BAIDU_API_KEY 未配置。")
    try:
        payload = {
            "messages": [{"content": "保健品 老人 被骗 最新", "role": "user"}],
            "edition": "standard",
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": 3}],
            "search_filter": {},
            "search_recency_filter": "month",
            "safe_search": False,
        }
        resp = await int_client.request(
            "POST",
            "https://qianfan.baidubce.com/v2/ai_search/web_search",
            headers={
                "Authorization": f"Bearer {BAIDU_API_KEY}",
                "Content-Type": "application/json; charset=utf-8",
                "X-Appbuilder-From": "superdirector",
            },
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=SOURCE_HEALTH_INT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        references = data.get("references") or []
        if references:
            return _source_ok("百度搜索可用。", sample_query="保健品 老人 被骗 最新", result_count=len(references[:3]))
        return _source_warning("百度搜索可访问，但当前测试查询无结果。", sample_query="保健品 老人 被骗 最新")
    except Exception as exc:  # noqa: BLE001
        return _source_error(f"百度搜索检查失败: {_exc_text(exc)}")


async def _check_tavily_source(ext_client) -> dict:
    if not TAVILY_ENABLED:
        return {"status": "disabled", "message": "Tavily 当前未启用。"}
    if not TAVILY_API_KEY:
        return _source_missing_key("TAVILY_API_KEY 未配置。")
    try:
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": "315 外泌体",
            "search_depth": "basic",
            "topic": "general",
            "max_results": TAVILY_RESULT_COUNT,
            "include_answer": False,
            "include_raw_content": False,
        }
        resp = await ext_client.request(
            "POST",
            TAVILY_ENDPOINT,
            headers={"Content-Type": "application/json; charset=utf-8"},
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=SOURCE_HEALTH_EXT_TIMEOUT,
        )
        resp.raise_for_status()
        results = (resp.json().get("results") or [])[: max(1, TAVILY_RESULT_COUNT)]
        if results:
            return _source_ok("Tavily 搜索可用。", sample_query="315 外泌体", result_count=len(results))
        return _source_warning("Tavily 可访问，但当前测试查询无结果。", sample_query="315 外泌体", result_count=0)
    except Exception as exc:  # noqa: BLE001
        return _source_error(f"Tavily 检查失败: {_exc_text(exc)}", sample_query="315 外泌体")


async def _check_official_source(ext_client, spec: dict) -> dict:
    try:
        resp = await ext_client.request(
            "GET",
            spec["url"],
            headers={**OFFICIAL_PAGE_HEADERS, "Referer": spec["url"]},
            follow_redirects=True,
            timeout=SOURCE_HEALTH_EXT_TIMEOUT,
        )
        resp.raise_for_status()
        items = _parse_html_listing(
            resp.text,
            base_url=spec["url"],
            source=spec["source"],
            keywords=spec["keywords"],
            url_patterns=spec.get("url_patterns"),
            limit=1,
        )
        if items:
            return _source_ok("页面可访问且能解析到条目。", item_count=len(items), url=spec["url"])
        return _source_warning("页面可访问，但当前未解析到匹配条目。", item_count=0, url=spec["url"])
    except Exception as exc:  # noqa: BLE001
        return _source_error(f"页面检查失败: {_exc_text(exc)}", url=spec["url"])


async def _check_official_api_source(ext_client, spec: dict) -> dict:
    try:
        resp = await ext_client.request(
            "GET",
            spec["url"],
            params=spec.get("params"),
            headers=OFFICIAL_PAGE_HEADERS,
            follow_redirects=True,
            timeout=SOURCE_HEALTH_EXT_TIMEOUT,
        )
        resp.raise_for_status()
        if spec["source"] == "fda_safety":
            items = _parse_fda_enforcement(resp.json(), source=spec["source"], limit=1)
        else:
            items = []
        if items:
            return _source_ok("官方 API 可访问且能解析到条目。", item_count=len(items), url=spec["url"])
        return _source_warning("官方 API 可访问，但当前未解析到条目。", item_count=0, url=spec["url"])
    except Exception as exc:  # noqa: BLE001
        if spec["source"] == "fda_safety" and exc.__class__.__name__ in {"ConnectTimeout", "ReadTimeout"}:
            return _source_warning(
                "FDA 官方 API 当前网络不可达，系统会继续使用 WHO、STAT 和 Brave 国际源补位。",
                url=spec["url"],
            )
        return _source_error(f"官方 API 检查失败: {_exc_text(exc)}", url=spec["url"])


def _check_mediacrawler_source(spec: dict) -> dict:
    latest = _latest_mediacrawler_file(spec["directories"])
    if not latest:
        return _source_warning("未找到本地缓存文件。")
    age_hours = round(
        (datetime.now(tz=UTC) - datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)).total_seconds() / 3600,
        2,
    )
    if age_hours <= max(MEDIA_CRAWLER_MAX_AGE_HOURS, 1):
        return _source_ok("本地缓存新鲜，可用于采集。", latest_file=str(latest), age_hours=age_hours)
    return _source_warning(
        "本地缓存存在，但已过期，下一次采集会尝试刷新。",
        latest_file=str(latest),
        age_hours=age_hours,
    )


async def _build_source_health(app_state) -> dict:
    wewe_health = await get_wewe_health(app_state.int_client)
    wewe_meta = dict(wewe_health)
    wewe_message = str(wewe_meta.pop("message", "") or "WeWe-RSS 正常。")
    if not wewe_health.get("enabled"):
        wewe_entry = _source_warning(wewe_message or "WeWe-RSS 未启用。", **wewe_meta)
    elif not wewe_health.get("reachable"):
        wewe_entry = _source_error(wewe_message or "WeWe-RSS 不可达。", **wewe_meta)
    elif wewe_health.get("needs_relogin"):
        wewe_entry = _source_warning(wewe_message or "WeWe-RSS 需要重新登录。", **wewe_meta)
    else:
        wewe_entry = _source_ok(wewe_message, **wewe_meta)

    rss_results = await asyncio.gather(
        *[
            _guard_source_check(spec["source"], _check_rss_source(app_state.int_client, spec))
            for spec in (RSS_SOURCES + list(RSS_DISCOVERY_BASKET_SOURCES))
        ]
    )
    rss_specs = RSS_SOURCES + list(RSS_DISCOVERY_BASKET_SOURCES)
    rss_health = {spec["source"]: result for spec, result in zip(rss_specs, rss_results, strict=False)}

    official_specs = (
        [("html", spec) for spec in OFFICIAL_HTML_SOURCES]
        + [("api", spec) for spec in OFFICIAL_API_SOURCES]
    )
    official_results = await asyncio.gather(
        *[
            _guard_source_check(spec["source"], _check_official_source(app_state.ext_client, spec))
            if kind == "html"
            else _guard_source_check(spec["source"], _check_official_api_source(app_state.ext_client, spec))
            for kind, spec in official_specs
        ]
    )
    official_health = {
        spec["source"]: result for (_kind, spec), result in zip(official_specs, official_results, strict=False)
    }

    mediacrawler_health = {spec["source"]: _check_mediacrawler_source(spec) for spec in MEDIA_CRAWLER_SOURCE_SPECS}

    return {
        "wewe_rss": wewe_entry,
        **rss_health,
        "brave_search": await _guard_source_check("brave_search", _check_brave_source(app_state.ext_client)),
        "tavily_search": await _guard_source_check("tavily_search", _check_tavily_source(app_state.ext_client)),
        "baidu_search": await _guard_source_check("baidu_search", _check_baidu_source(app_state.int_client)),
        **official_health,
        **mediacrawler_health,
    }


@router.get("/health")
async def health():
    return {"ok": True}


@router.get("/schedule")
async def schedule_list():
    jobs = await list_schedule_jobs()
    return {"jobs": [_serialize_schedule_job(job) for job in jobs]}


@router.post("/schedule/update")
async def schedule_update(request: Request):
    payload = await request.json()
    job_id = str(payload.get("job_id") or "").strip()
    hour = payload.get("hour")
    minute = payload.get("minute")
    enabled = _parse_optional_bool(payload.get("enabled"))
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    if hour is None and minute is None and enabled is None:
        raise HTTPException(status_code=400, detail="hour, minute, or enabled is required")
    if hour is not None and not 0 <= int(hour) <= 23:
        raise HTTPException(status_code=400, detail="hour must be between 0 and 23")
    if minute is not None and not 0 <= int(minute) <= 59:
        raise HTTPException(status_code=400, detail="minute must be between 0 and 59")

    async with AsyncSessionLocal() as session:
        job = await crud.update_schedule_job(
            session,
            job_id,
            hour=int(hour) if hour is not None else None,
            minute=int(minute) if minute is not None else None,
            enabled=enabled,
        )
        if not job:
            raise HTTPException(status_code=404, detail="Schedule job not found")
    await refresh_schedule_job(job_id)
    jobs = await list_schedule_jobs()
    return {"jobs": [_serialize_schedule_job(job) for job in jobs]}


@router.post("/schedule/run/{job_id}")
async def schedule_run(job_id: str):
    jobs = {job.job_id for job in await list_schedule_jobs()}
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Schedule job not found")
    result = await run_schedule_job_now(job_id)
    return result


@router.post("/pipeline/run")
async def pipeline_run(request: Request):
    result = await run_pipeline(request.app.state)
    return result


@router.get("/scoring/config")
async def scoring_config():
    config = get_scoring_config()
    config["editorial"] = editorial_config_summary()
    return config


@router.get("/editorial/config")
async def editorial_config():
    return editorial_config_summary()


@router.get("/editorial/backtest")
async def editorial_backtest():
    async with AsyncSessionLocal() as session:
        return await run_editorial_backtest(session)


@router.get("/topics/{topic_id}/score-explain")
async def topic_score_explain(topic_id: str):
    async with AsyncSessionLocal() as session:
        row = await crud.get_topic_by_topic_id(session, topic_id)
        if not row:
            raise HTTPException(status_code=404, detail="Topic not found")

    scores = {
        "emotion": row.score_emotion,
        "timely": row.score_timely,
        "subvert": row.score_subvert,
        "relate": row.score_relate,
        "spread": row.score_spread,
        "tension": row.score_tension,
        "depth": row.score_depth,
    }
    explanation = explain_scores(scores, row.source)
    explanation["topic"] = {
        "topic_id": row.topic_id,
        "title": row.title,
        "source": row.source,
        "current_platform_priority": row.platform_priority,
        "current_score_total": row.score_total,
        "topic_line_primary": row.topic_line_primary,
        "topic_line_secondary": row.topic_line_secondary,
        "content_role": row.content_role,
        "creator_fit": row.creator_fit,
        "li_jie_value": row.li_jie_value,
        "zhang_auntie_value": row.zhang_auntie_value,
        "audience_core": row.audience_core,
        "compliance_risk": row.compliance_risk,
        "actionability_risk": row.actionability_risk,
        "topic_cluster": row.topic_cluster,
        "reject_type": row.reject_type,
        "rejection_reason": row.rejection_reason,
        "timeliness_window": row.timeliness_window,
        "platform_fit": row.platform_fit,
        "decision_impact_level": row.decision_impact_level,
        "selection_rank_reason": row.selection_rank_reason,
        "editorial_priority_score": row.editorial_priority_score,
    }
    return explanation


@router.post("/scoring/tune")
async def scoring_tune(request: Request):
    payload = await request.json()
    instruction = str(payload.get("instruction") or "").strip()
    apply_changes = bool(payload.get("apply", False))
    rescore_latest = bool(payload.get("rescore_latest", False))
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")

    patch, usage, errors = await interpret_scoring_instruction(
        request.app.state.ext_client,
        request.app.state.int_client,
        instruction,
    )
    if errors:
        return {
            "instruction": instruction,
            "patch": patch,
            "usage": usage,
            "errors": errors,
            "applied": False,
        }

    preview = create_scoring_preview(instruction=instruction, patch=patch, usage=usage)
    applied_result = None
    rescored_topics: list[dict] = []
    if apply_changes:
        create_scoring_snapshot(
            reason="before_apply",
            instruction=instruction,
            patch=patch,
            actor="api.scoring_tune",
        )
        applied_result = apply_scoring_patch(patch)
        if usage:
            async with AsyncSessionLocal() as session:
                await crud.log_cost(
                    session,
                    provider=usage.get("provider") or "unknown",
                    model=usage.get("model") or "unknown",
                    endpoint=usage.get("endpoint") or "scoring.tune",
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    cost_usd=usage.get("cost_usd") or usage.get("estimated_cost_usd"),
                )

        if rescore_latest:
            rescored_topics = await _rescore_latest_topics()

    estimated = {
        **usage,
        "per_call_hint": (
            "通常一次自然语言调权约 500-1200 输入 tokens，100-300 输出 tokens；"
            "按当前 qwen-plus 定价，常见一次约 $0.0001 - $0.0003。"
            if usage.get("provider") == "qwen"
            else "通常一次自然语言调权约 500-1200 输入 tokens，100-300 输出 tokens；"
            "按 Gemini Flash 常见价，通常低于 $0.001。"
        ),
    }
    return {
        "instruction": instruction,
        "patch": patch,
        "usage": estimated,
        "errors": errors,
        "applied": bool(apply_changes),
        "preview": preview,
        "apply_result": applied_result,
        "rescored_topics": rescored_topics,
    }


async def _rescore_latest_topics() -> list[dict]:
    rescored_topics: list[dict] = []
    async with AsyncSessionLocal() as session:
        latest_run = await crud.get_latest_completed_run(session)
        if not latest_run:
            return rescored_topics
        rows = await crud.get_topics_for_run(session, latest_run.id)
        rescoring_input = []
        for row in rows:
            rescoring_input.append(
                {
                    "topic_id": row.topic_id,
                    "source": row.source,
                    "scores": {
                        "emotion": row.score_emotion,
                        "timely": row.score_timely,
                        "subvert": row.score_subvert,
                        "relate": row.score_relate,
                        "spread": row.score_spread,
                        "tension": row.score_tension,
                        "depth": row.score_depth,
                    },
                }
            )
        rescored, _score_details = score_topics(rescoring_input)
        for topic in rescored:
            updated = await crud.update_topic_scoring(
                session,
                topic["topic_id"],
                score_total=topic.get("score_total") or 0.0,
                platform_priority=topic.get("platform_priority"),
            )
            if updated:
                rescored_topics.append(
                    {
                        "topic_id": updated.topic_id,
                        "title": updated.title,
                        "score_total": updated.score_total,
                        "platform_priority": updated.platform_priority,
                    }
                )
    return rescored_topics


@router.post("/scoring/tune/confirm")
async def scoring_tune_confirm(request: Request):
    payload = await request.json()
    preview_id = str(payload.get("preview_id") or "").strip()
    rescore_latest = bool(payload.get("rescore_latest", False))
    if not preview_id:
        raise HTTPException(status_code=400, detail="preview_id is required")

    try:
        preview = load_scoring_preview(preview_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    patch = preview.get("patch") or {}
    instruction = preview.get("instruction") or ""
    create_scoring_snapshot(
        reason="before_confirm_apply",
        instruction=instruction,
        patch=patch,
        actor="api.scoring_tune_confirm",
    )
    applied_result = apply_scoring_patch(patch)
    rescored_topics = await _rescore_latest_topics() if rescore_latest else []

    return {
        "preview_id": preview_id,
        "instruction": instruction,
        "applied": True,
        "apply_result": applied_result,
        "rescored_topics": rescored_topics,
    }


@router.post("/scoring/apply-review-patch")
async def scoring_apply_review_patch(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    sd_weight_patch = payload.get("sd_weight_patch") or {}
    style_patch = payload.get("style_patch") or []
    if not sd_weight_patch and not style_patch:
        raise HTTPException(status_code=400, detail="sd_weight_patch or style_patch is required")

    snapshot = create_scoring_snapshot(
        reason="apply_review_patch",
        instruction="hotmic review-engine patch",
        patch=payload,
        actor="api.apply_review_patch",
    )
    apply_result = apply_review_patch(payload)
    return {
        "applied": True,
        "snapshot": snapshot,
        "apply_result": apply_result,
    }


@router.get("/scoring/history")
async def scoring_history(limit: int = 10):
    return {"items": list_scoring_history(limit=limit)}


@router.post("/scoring/rollback")
async def scoring_rollback(request: Request):
    payload = await request.json()
    snapshot_id = str(payload.get("snapshot_id") or "").strip()
    rescore_latest = bool(payload.get("rescore_latest", False))
    if not snapshot_id:
        raise HTTPException(status_code=400, detail="snapshot_id is required")

    create_scoring_snapshot(
        reason="before_rollback",
        instruction=snapshot_id,
        actor="api.scoring_rollback",
    )
    try:
        restored = restore_scoring_snapshot(snapshot_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    rescored_topics = await _rescore_latest_topics() if rescore_latest else []
    return {
        "snapshot_id": snapshot_id,
        "restored": True,
        "restore_result": restored,
        "rescored_topics": rescored_topics,
    }


@router.get("/topics/today")
async def topics_today():
    latest_run = None
    async with AsyncSessionLocal() as session:
        latest_run = await crud.get_latest_completed_run(session, date_str=today_str())
        if latest_run:
            rows = await crud.get_output_topics_for_run(session, latest_run.id, limit=TOP_N)
        else:
            rows = []
    return {
        "date": today_str(),
        "run_id": latest_run.id if rows else None,
        "topics": [_serialize_topic(r) for r in rows],
        "errors": [],
    }


@router.get("/topics/recent")
async def topics_recent(days: int = 7, limit: int = 5):
    days = max(1, min(days, 30))
    limit = max(1, min(limit, 20))
    async with AsyncSessionLocal() as session:
        rows = await crud.get_recent_top_topics(session, since_days=days, limit=limit)
    return {
        "days": days,
        "limit": limit,
        "topics": [_serialize_topic(r) for r in rows],
        "errors": [],
    }


@router.post("/topics/{topic_id}/regen")
async def topics_regen(topic_id: str, request: Request):
    async with AsyncSessionLocal() as session:
        stmt = select(Topic).where(Topic.topic_id == topic_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Topic not found")

    base_topic = {
        "topic_id": row.topic_id,
        "date": row.date,
        "title": row.title,
        "url": row.url,
        "source": row.source,
        "timestamp": row.timestamp,
        "raw_snippet": row.raw_snippet,
    }

    analyzed, analyze_errors, _usage_a = await analyze_topics(
        request.app.state.ext_client,
        request.app.state.int_client,
        [base_topic],
    )
    if not analyzed:
        raise HTTPException(status_code=500, detail="Analyzer returned no results")

    analyzed[0]["topic_id"] = row.topic_id
    analyzed[0]["date"] = row.date
    analyzed[0]["errors"] = (analyzed[0].get("errors") or []) + analyze_errors

    scored, score_details = score_topics(analyzed)
    framed, frame_errors, _usage_f = await generate_frames(
        request.app.state.ext_client,
        request.app.state.int_client,
        scored,
    )

    errors = analyze_errors + frame_errors
    for t in framed:
        t["date"] = row.date
        t["pipeline_run_id"] = row.pipeline_run_id
        t["model_version"] = QWEN_MODEL if QWEN_API_KEY else GEMINI_FLASH_MODEL
        t["errors"] = (t.get("errors") or []) + errors
        t["status"] = "ok" if not t["errors"] else "failed"

    async with AsyncSessionLocal() as session:
        rows = await crud.insert_topics(session, framed)
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

    return {"topic": framed[0] if framed else None, "errors": errors}


@router.post("/topics/{topic_id}/frame/{platform}")
async def topics_frame(topic_id: str, platform: str, request: Request):
    async with AsyncSessionLocal() as session:
        stmt = select(Topic).where(Topic.topic_id == topic_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Topic not found")

    topic = {
        "topic_id": row.topic_id,
        "title": row.title,
        "summary": row.summary,
        "platform_priority": platform,
        "score_total": row.score_total,
    }
    framed, errors, _usage = await generate_frames(
        request.app.state.ext_client, request.app.state.int_client, [topic]
    )
    return {"topic": framed[0] if framed else None, "errors": errors}


@router.post("/topics/{topic_id}/create-script")
async def topics_create_script(topic_id: str, request: Request):
    payload: dict = {}
    try:
        maybe_payload = await request.json()
        if isinstance(maybe_payload, dict):
            payload = maybe_payload
    except Exception:  # noqa: BLE001
        payload = {}

    platform_override = payload.get("platform")
    async with AsyncSessionLocal() as session:
        row = await crud.get_topic_by_topic_id(session, topic_id)
    if not row:
        raise HTTPException(status_code=404, detail="Topic not found")

    hotmic_input = _build_hotmic_script_payload(row, platform_override=platform_override)
    return {
        "topic": _serialize_topic(row),
        "hotmic_input": hotmic_input,
        "hotmic_launch_command": _build_hotmic_launch_command(),
    }


@router.post("/topics/today/{rank}/create-script")
async def topics_today_create_script(rank: int, request: Request):
    payload: dict = {}
    try:
        maybe_payload = await request.json()
        if isinstance(maybe_payload, dict):
            payload = maybe_payload
    except Exception:  # noqa: BLE001
        payload = {}

    _run, row = await _resolve_today_ranked_topic(rank)
    hotmic_input = _build_hotmic_script_payload(row, platform_override=payload.get("platform"))
    launch_command = _build_hotmic_launch_command()
    return {
        "rank": rank,
        "topic": _serialize_topic(row),
        "hotmic_input": hotmic_input,
        "hotmic_launch_command": launch_command,
        "telegram_message": _telegram_script_message(
            rank=rank,
            row=row,
            hotmic_input=hotmic_input,
            launch_command=launch_command,
        ),
    }


@router.post("/topics/{topic_id}/publish-confirm")
async def topics_publish_confirm(topic_id: str, request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")
    return await _confirm_publish_for_topic(
        topic_id=topic_id,
        payload=payload,
        ext_client=request.app.state.ext_client,
    )


@router.post("/topics/today/{rank}/publish-confirm")
async def topics_today_publish_confirm(rank: int, request: Request):
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    _run, row = await _resolve_today_ranked_topic(rank)
    result = await _confirm_publish_for_topic(
        topic_id=row.topic_id,
        payload=payload,
        ext_client=request.app.state.ext_client,
    )
    result["rank"] = rank
    result["telegram_message"] = _telegram_publish_message(
        rank=rank,
        row=result["topic"],
        script_path=result.get("script_path"),
    )
    return result


@router.get("/cost")
async def cost_summary():
    async with AsyncSessionLocal() as session:
        today = date.today()
        start_day = datetime.combine(today, datetime.min.time())
        start_month = datetime.combine(today.replace(day=1), datetime.min.time())

        stmt_today = select(
            func.count(ApiCostLog.id),
            func.coalesce(func.sum(ApiCostLog.cost_usd), 0.0),
        ).where(ApiCostLog.timestamp >= start_day)
        stmt_month = select(
            func.count(ApiCostLog.id),
            func.coalesce(func.sum(ApiCostLog.cost_usd), 0.0),
        ).where(ApiCostLog.timestamp >= start_month)

        result_today = await session.execute(stmt_today)
        today_calls, today_cost = result_today.one()

        result_month = await session.execute(stmt_month)
        month_calls, month_cost = result_month.one()

        stmt_details = (
            select(
                func.date(ApiCostLog.timestamp),
                func.count(ApiCostLog.id),
                func.coalesce(func.sum(ApiCostLog.cost_usd), 0.0),
            )
            .group_by(func.date(ApiCostLog.timestamp))
            .order_by(func.date(ApiCostLog.timestamp).desc())
            .limit(31)
        )
        result_details = await session.execute(stmt_details)
        details = []
        for day, calls, cost in result_details.all():
            details.append({"date": day, "calls": calls or 0, "cost_usd": cost or 0.0})

    return {
        "today": {"calls": today_calls or 0, "cost_usd": today_cost or 0.0},
        "month": {"calls": month_calls or 0, "cost_usd": month_cost or 0.0},
        "details": details,
    }


@router.post("/feedback/sync")
async def feedback_sync(request: Request):
    summary = await sync_feedback_from_bitable(request.app.state.ext_client)
    return summary


@router.post("/feedback/collect")
async def feedback_collect(request: Request, platform: str = "douyin"):
    normalized = str(platform or "douyin").strip().lower()
    if normalized == "douyin":
        return await collect_douyin_feedback(request.app.state.int_client)
    if normalized == "xiaohongshu":
        return await collect_xhs_feedback(request.app.state.int_client)
    if normalized == "shipinhao":
        return {
            "status": "skipped",
            "platform": "shipinhao",
            "message": "Shipinhao currently uses manual Bitable sync. Please fill Bitable and run /feedback/sync.",
        }
    if normalized == "all":
        return {
            "douyin": await collect_douyin_feedback(request.app.state.int_client),
            "xiaohongshu": await collect_xhs_feedback(request.app.state.int_client),
            "shipinhao": {
                "status": "skipped",
                "platform": "shipinhao",
                "message": "Shipinhao currently uses manual Bitable sync. Please fill Bitable and run /feedback/sync.",
            },
        }
    raise HTTPException(status_code=400, detail="platform must be douyin, xiaohongshu, shipinhao, or all")


@router.get("/feedback/status")
async def feedback_status():
    return await feedback_status_summary()


@router.post("/feedback/douyin-cookie")
async def feedback_douyin_cookie(request: Request):
    payload = await request.json()
    cookie = str(payload.get("cookie") or "").strip()
    if not cookie:
        raise HTTPException(status_code=400, detail="cookie is required")
    path = save_douyin_cookie(cookie)
    return {
        "saved": True,
        "cookie_configured": douyin_cookie_exists(),
        "path": str(path),
    }


@router.get("/feedback/summary")
async def feedback_summary():
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Topic)
            .where(
                (Topic.publish_status.is_not(None))
                | (Topic.publish_url.is_not(None))
                | (Topic.publish_at.is_not(None))
                | (Topic.perf_watch_rate.is_not(None))
                | (Topic.perf_favorite_rate.is_not(None))
                | (Topic.perf_comments.is_not(None))
                | (Topic.perf_shares.is_not(None))
            )
            .order_by(Topic.updated_at.desc())
            .limit(20)
        )
        rows = (await session.execute(stmt)).scalars().all()

    items = []
    for row in rows:
        items.append(
            {
                "topic_id": row.topic_id,
                "title": row.title,
                "platform_priority": row.platform_priority,
                "publish_status": row.publish_status,
                "publish_url": row.publish_url,
                "publish_at": row.publish_at,
                "perf_watch_rate": row.perf_watch_rate,
                "perf_favorite_rate": row.perf_favorite_rate,
                "perf_comments": row.perf_comments,
                "perf_shares": row.perf_shares,
                "creator_notes": row.creator_notes,
                "review_status": row.review_status,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )

    return {
        "enabled": feedback_sync_enabled(),
        "count": len(items),
        "items": items,
    }


@router.get("/status")
async def status(request: Request):
    async with AsyncSessionLocal() as session:
        display_stmt = (
            select(PipelineRun)
            .where(PipelineRun.topics_count > 0)
            .order_by(desc(PipelineRun.id))
            .limit(1)
        )
        active_stmt = (
            select(PipelineRun)
            .where(PipelineRun.status == "running")
            .order_by(desc(PipelineRun.id))
            .limit(1)
        )
        display_run = (await session.execute(display_stmt)).scalar_one_or_none()
        active_run = (await session.execute(active_stmt)).scalar_one_or_none()
        run = display_run or active_run
        topic_stmt = select(Topic.source).where(Topic.pipeline_run_id == run.id) if run else None
        topic_result = await session.execute(topic_stmt) if topic_stmt is not None else None
        sources = [row[0] for row in topic_result.all()] if topic_result is not None else []
    if not run:
        return {"status": "no_runs"}
    errors = _json_loads(run.errors_json) or []
    has_rss_topics = any(str(source).endswith("_rss") or str(source).startswith("rss_") for source in sources)
    has_brave_topics = any(str(source).startswith("brave") for source in sources)
    has_official_topics = any(
        source in {"nmpa_news", "govcn_policy", "fda_safety", "who_alerts", "stat_pharma"}
        for source in sources
    )
    collector_rss = _module_status_from_errors(
        errors=errors,
        prefix="RSS fetch failed",
        total_sources=len(RSS_SOURCES) + len(RSS_DISCOVERY_BASKET_SOURCES),
        has_selected_topics=has_rss_topics,
    )
    collector_brave = _module_status_from_errors(
        errors=errors,
        prefix="Brave fetch failed",
        total_sources=len(BRAVE_QUERY_SPECS),
        has_selected_topics=has_brave_topics,
        missing_key=not BRAVE_SEARCH_API_KEYS,
    )
    collector_official = _module_status_from_errors(
        errors=errors,
        prefix="Official source fetch failed",
        total_sources=len(OFFICIAL_HTML_SOURCES),
        has_selected_topics=has_official_topics,
    )

    wewe_health = await get_wewe_health(request.app.state.int_client)

    display_errors = []
    for error in errors:
        text = str(error)
        if text.startswith("RSS fetch failed") and collector_rss == "ok":
            continue
        if text.startswith("Official source fetch failed") and collector_official == "ok":
            continue
        if (
            text.startswith("Brave fetch failed") or text.startswith("BRAVE_SEARCH_API_KEY missing")
        ) and collector_brave == "ok":
            continue
        display_errors.append(error)

    if is_mock_mode():
        analyzer = "mock"
    elif QWEN_API_KEY:
        analyzer = "qwen"
    else:
        analyzer = "gemini"

    return {
        "service": "running",
        "last_run": {
            "id": run.id,
            "date": run.started_at.date().isoformat() if run.started_at else None,
            "topics_count": run.topics_count,
            "status": _display_run_status(run, errors),
        },
        "modules": {
            "collector_rss": collector_rss,
            "collector_official": collector_official,
            "collector_brave": collector_brave,
            "analyzer": analyzer,
            "db": "ok",
        },
        "config": {
            "model": QWEN_MODEL if QWEN_API_KEY else GEMINI_FLASH_MODEL,
            "top_n": TOP_N,
        },
        "active_run": {
            "id": active_run.id,
            "date": active_run.started_at.date().isoformat() if active_run and active_run.started_at else None,
            "status": active_run.status,
        }
        if active_run
        else None,
        "errors": display_errors,
        "source_health": {"wewe_rss": wewe_health},
    }


@router.get("/sources/health")
async def source_health(request: Request):
    return await _build_source_health(request.app.state)


@router.post("/sources/wewe/login-qr")
async def source_wewe_login_qr(request: Request):
    baseline_health = await get_wewe_health(request.app.state.int_client)
    result = await create_wewe_login_qr(request.app.state.int_client)
    uuid = str(result.get("uuid") or "").strip()
    if result.get("created") and uuid:
        tasks = getattr(request.app.state, "wewe_login_watch_tasks", None)
        if not isinstance(tasks, dict):
            tasks = {}
            request.app.state.wewe_login_watch_tasks = tasks
        existing = tasks.get(uuid)
        if existing and not existing.done():
            existing.cancel()
        tasks[uuid] = asyncio.create_task(
            _watch_wewe_login_and_notify(request.app.state, uuid, baseline_health)
        )
    return result


@router.get("/sources/wewe/login-qr/{uuid}.png")
async def source_wewe_login_qr_png(uuid: str):
    scan_url = build_wewe_scan_url(uuid)
    if not scan_url:
        raise HTTPException(status_code=404, detail="Missing uuid")
    image_bytes = build_wewe_qr_png(scan_url)
    if not image_bytes:
        raise HTTPException(status_code=404, detail="Unable to build QR image")
    return Response(content=image_bytes, media_type="image/png")


@router.get("/sources/wewe/login-result/{uuid}")
async def source_wewe_login_result(uuid: str, request: Request):
    return await get_wewe_login_result(request.app.state.int_client, uuid)


@router.post("/sources/wewe/login-await/{uuid}")
async def source_wewe_login_await(uuid: str, request: Request):
    return await await_wewe_login_and_add(request.app.state.int_client, uuid)


@router.post("/sources/wewe/account/add")
async def source_wewe_account_add(payload: dict, request: Request):
    account_id = str(payload.get("id") or "")
    token = payload.get("token") or ""
    name = payload.get("name") or ""
    if not account_id or not token or not name:
        raise HTTPException(status_code=400, detail="Missing id, token, or name")
    return await add_wewe_account(
        request.app.state.int_client,
        account_id=account_id,
        token=token,
        name=name,
    )
