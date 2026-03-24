from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from compat import UTC
from config import (
    FEEDBACK_WEEKLY_DIR,
    FEEDBACK_WEEKLY_LOOKBACK_DAYS,
    FEEDBACK_WEEKLY_MAX_TOPICS,
    FEEDBACK_WEEKLY_MIN_SAMPLES,
    FEEDBACK_WEEKLY_MIN_TOPICS,
    FEEDBACK_WEEKLY_PENDING_PATCH_PATH,
    HOTMIC_REVIEW_ENGINE_DIR,
    load_casey_profile,
)
from db import crud
from db.session import AsyncSessionLocal
from pipeline.feedback_collector import collect_douyin_feedback
from tools.telegram_sender import send_casey_message


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _utc_stamp() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%SZ")


def _topic_value(topic: Any, key: str, default: Any = None) -> Any:
    if isinstance(topic, dict):
        return topic.get(key, default)
    return getattr(topic, key, default)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    text = str(value or "").strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text}T00:00:00")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _normalize_completion_rate(value: Any) -> float | None:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return None
    if rate < 0:
        return None
    if rate > 1:
        rate = rate / 100.0
    return round(min(rate, 1.0), 4)


def _line_label_map() -> dict[str, str]:
    profile = load_casey_profile()
    lines = ((profile.get("content_mix") or {}).get("lines") or [])
    mapping: dict[str, str] = {}
    for entry in lines:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if key:
            mapping[key] = str(entry.get("name") or key).strip()
    return mapping


def _role_label_map() -> dict[str, str]:
    profile = load_casey_profile()
    roles = ((profile.get("content_mix") or {}).get("roles") or [])
    mapping = {
        "spread": "传播款",
        "save": "收藏款",
        "followup": "追问款",
    }
    for entry in roles:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if key:
            mapping[key] = str(entry.get("name") or mapping.get(key) or key).strip()
    return mapping


def _topic_reference_time(topic: Any) -> datetime | None:
    return (
        _coerce_datetime(_topic_value(topic, "publish_at"))
        or _coerce_datetime(_topic_value(topic, "updated_at"))
        or _coerce_datetime(_topic_value(topic, "created_at"))
        or _coerce_datetime(_topic_value(topic, "date"))
    )


def _eligible_feedback_topic(topic: Any) -> bool:
    views = _topic_value(topic, "perf_views")
    completion_rate = _normalize_completion_rate(_topic_value(topic, "perf_watch_rate"))
    try:
        views_count = int(views or 0)
    except (TypeError, ValueError):
        views_count = 0
    return views_count > 0 and completion_rate is not None


async def load_feedback_review_topics(
    *,
    platform: str = "douyin",
    since_days: int = FEEDBACK_WEEKLY_LOOKBACK_DAYS,
    limit: int = FEEDBACK_WEEKLY_MAX_TOPICS,
) -> list[Any]:
    async with AsyncSessionLocal() as session:
        rows = await crud.list_topics_for_feedback(session, platform=platform, limit=limit)

    cutoff = _utc_now() - timedelta(days=max(since_days, 1))
    eligible: list[Any] = []
    for row in rows:
        if not _eligible_feedback_topic(row):
            continue
        reference_time = _topic_reference_time(row)
        if reference_time and reference_time < cutoff:
            continue
        eligible.append(row)

    eligible.sort(key=lambda item: _topic_reference_time(item) or datetime.min.replace(tzinfo=UTC))
    return eligible


def build_review_dataset(
    topics: list[Any],
    *,
    platform: str = "douyin",
) -> dict[str, Any]:
    line_map = _line_label_map()
    role_map = _role_label_map()
    entries: list[dict[str, Any]] = []

    for topic in topics:
        published_at = _topic_reference_time(topic)
        completion_rate = _normalize_completion_rate(_topic_value(topic, "perf_watch_rate"))
        if completion_rate is None:
            continue
        entries.append(
            {
                "topic_id": str(_topic_value(topic, "topic_id") or ""),
                "title": str(_topic_value(topic, "title") or "").strip(),
                "date": (
                    published_at.astimezone(UTC).date().isoformat()
                    if published_at
                    else str(_topic_value(topic, "date") or "")
                ),
                "publish_time": published_at.astimezone(UTC).strftime("%H:%M") if published_at else "",
                "content_line": line_map.get(
                    str(_topic_value(topic, "topic_line_primary") or "").strip(),
                    str(_topic_value(topic, "topic_line_primary") or "未分类").strip(),
                ),
                "content_type": role_map.get(
                    str(_topic_value(topic, "content_role") or "").strip(),
                    str(_topic_value(topic, "content_role") or "").strip(),
                ),
                "views": int(_topic_value(topic, "perf_views") or 0),
                "likes": int(_topic_value(topic, "perf_likes") or 0),
                "comments": int(_topic_value(topic, "perf_comments") or 0),
                "shares": int(_topic_value(topic, "perf_shares") or 0),
                "saves": int(_topic_value(topic, "perf_collects") or 0),
                "completion_rate": completion_rate,
                "followers_gained": 0,
                "publish_url": str(_topic_value(topic, "publish_url") or "").strip(),
            }
        )

    return {
        "platform": platform,
        "generated_at": _utc_now().replace(microsecond=0).isoformat(),
        "entries": entries,
    }


def _write_json(path: str | Path, payload: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)


@lru_cache(maxsize=1)
def _generate_patches_module():
    script_path = Path(HOTMIC_REVIEW_ENGINE_DIR) / "scripts" / "generate_patches.py"
    if not script_path.exists():
        raise FileNotFoundError(f"HotMic review-engine script not found: {script_path}")

    spec = importlib.util.spec_from_file_location("hotmic_generate_patches", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load HotMic review-engine script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate_review_patch_bundle(
    dataset: dict[str, Any],
    *,
    output_dir: str | Path = FEEDBACK_WEEKLY_DIR,
    min_samples: int = FEEDBACK_WEEKLY_MIN_SAMPLES,
) -> dict[str, Any]:
    target_dir = Path(output_dir)
    stamp = _utc_stamp()
    dataset_path = target_dir / f"content_data_{stamp}.json"
    patch_path = target_dir / f"patches_{stamp}.json"
    pending_path = Path(FEEDBACK_WEEKLY_PENDING_PATCH_PATH)

    _write_json(dataset_path, dataset)
    module = _generate_patches_module()
    patch_payload = module.generate_patches(str(dataset_path), str(patch_path), min_samples)
    _write_json(pending_path, patch_payload)

    return {
        "dataset_path": str(dataset_path),
        "patch_path": str(patch_path),
        "pending_path": str(pending_path),
        "patch": patch_payload,
    }


def _summarize_patch_lines(patch: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    weight_patch = patch.get("sd_weight_patch") or {}
    style_patch = patch.get("style_patch") or []

    if weight_patch:
        lines.append("权重建议：")
        for line_name, item in weight_patch.items():
            if not isinstance(item, dict):
                continue
            delta = float(item.get("delta") or 0.0)
            reason = str(item.get("reason") or "").strip()
            lines.append(f"- {line_name}: {delta:+.2f} {reason}".strip())

    if style_patch:
        lines.append("风格建议：")
        for item in style_patch[:3]:
            if not isinstance(item, dict):
                continue
            confidence = float(item.get("confidence") or 0.0)
            action = str(item.get("action") or item.get("rule") or "").strip()
            if action:
                lines.append(f"- [{confidence:.2f}] {action}")

    if not lines:
        lines.append("本周样本已复盘，但暂未触发新的权重或风格 patch。")
    return lines


async def run_feedback_weekly_cycle(client) -> dict[str, Any]:
    collect_summary = await collect_douyin_feedback(client)
    eligible_topics = await load_feedback_review_topics()

    if len(eligible_topics) < FEEDBACK_WEEKLY_MIN_TOPICS:
        status = "failed" if collect_summary.get("status") == "failed" else "skipped"
        return {
            "status": status,
            "collect_summary": collect_summary,
            "eligible_topics": len(eligible_topics),
            "message": (
                f"反馈样本不足，近 {FEEDBACK_WEEKLY_LOOKBACK_DAYS} 天仅 {len(eligible_topics)} 条有效 topic，"
                f"未达到阈值 {FEEDBACK_WEEKLY_MIN_TOPICS}。"
            ),
        }

    dataset = build_review_dataset(eligible_topics)
    bundle = generate_review_patch_bundle(dataset)
    patch = bundle["patch"]
    weight_patch = patch.get("sd_weight_patch") or {}
    style_patch = patch.get("style_patch") or []

    message_lines = [
        "Casey 汇报：本周 feedback review 已完成，patch 已生成，暂未自动应用。",
        f"有效样本：{len(dataset.get('entries') or [])} 条（近 {FEEDBACK_WEEKLY_LOOKBACK_DAYS} 天）",
        f"抖音回收状态：{collect_summary.get('status')}",
        f"权重 patch：{len(weight_patch)} 条｜风格 patch：{len(style_patch)} 条",
        *(_summarize_patch_lines(patch)),
        f"待确认文件：{bundle['pending_path']}",
        "确认后可调用 /scoring/apply-review-patch 手动应用。",
    ]

    notify_result: dict[str, Any] | None = None
    notify_error: str | None = None
    try:
        notify_result = await send_casey_message(client, "\n".join(message_lines))
    except Exception as exc:  # noqa: BLE001
        notify_error = str(exc)

    status = "ok" if notify_error is None else "partial"
    return {
        "status": status,
        "collect_summary": collect_summary,
        "eligible_topics": len(eligible_topics),
        "dataset_path": bundle["dataset_path"],
        "patch_path": bundle["patch_path"],
        "pending_path": bundle["pending_path"],
        "weight_patch_count": len(weight_patch),
        "style_patch_count": len(style_patch),
        "notified": notify_error is None,
        "notify_error": notify_error,
        "notify_result": notify_result,
    }
