from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from core.config import BITABLE_APP_TOKEN, FEISHU_BASE_URL, FRAMES_TABLE_ID, TOPICS_TABLE_ID
from db.session import AsyncSessionLocal
from db import crud
from pipeline.utils import request_with_retry
from integrations.feishu_auth import feishu_enabled, get_tenant_access_token

_MAX_BATCH_SIZE = 100
_TOPICS_PRIMARY_FIELD = "文本"
_FRAMES_PRIMARY_FIELD = "多行文本"
_TOPIC_TEXT_FIELDS = {
    _TOPICS_PRIMARY_FIELD,
    "topic_id",
    "date",
    "angle_type",
    "platform_priority",
    "content_type",
    "status",
    "url",
    "source",
    "timestamp",
    "summary",
    "keywords",
    "competitor_angle",
    "angle_gap",
    "model_version",
    "publish_status",
    "publish_url",
    "publish_at",
    "frame_status",
    "frame_rejection_reason",
    "creator_notes",
    "publish_match_terms",
    "review_status",
    "errors",
    "synced_at",
}
_FRAME_TEXT_FIELDS = {
    _FRAMES_PRIMARY_FIELD,
    "topic_id",
    "date",
    "platform_priority",
    "hook",
    "outline",
    "cta",
    "monetize_hook",
    "platform_tips",
    "model_version",
    "status",
    "errors",
    "synced_at",
}


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _topics_table_ready() -> bool:
    return bool(BITABLE_APP_TOKEN and TOPICS_TABLE_ID)


def _frames_table_ready() -> bool:
    return bool(BITABLE_APP_TOKEN and FRAMES_TABLE_ID)


def bitable_sync_enabled() -> bool:
    return feishu_enabled() and bool(BITABLE_APP_TOKEN) and bool(TOPICS_TABLE_ID or FRAMES_TABLE_ID)


def _topic_fields(topic: dict) -> dict[str, Any]:
    return _coerce_text_fields(
        {
        _TOPICS_PRIMARY_FIELD: topic.get("title"),
        "topic_id": topic.get("topic_id"),
        "date": topic.get("date"),
        "angle_type": topic.get("angle_type"),
        "platform_priority": topic.get("platform_priority"),
        "content_type": topic.get("content_type"),
        "status": topic.get("status"),
        "url": topic.get("url"),
        "source": topic.get("source"),
        "timestamp": topic.get("timestamp"),
        "summary": topic.get("summary"),
        "keywords": _json_text(topic.get("keywords")),
        "competitor_angle": topic.get("competitor_angle"),
        "angle_gap": topic.get("angle_gap"),
        "score_total": topic.get("score_total"),
        "score_emotion": topic.get("score_emotion"),
        "score_timely": topic.get("score_timely"),
        "score_subvert": topic.get("score_subvert"),
        "score_relate": topic.get("score_relate"),
        "score_spread": topic.get("score_spread"),
        "score_tension": topic.get("score_tension"),
        "score_depth": topic.get("score_depth"),
        "pipeline_run_id": topic.get("pipeline_run_id"),
        "model_version": topic.get("model_version"),
        "publish_status": topic.get("publish_status"),
        "publish_url": topic.get("publish_url"),
        "publish_at": topic.get("publish_at"),
        "frame_status": topic.get("frame_status"),
        "frame_rejection_reason": topic.get("frame_rejection_reason"),
        "perf_views": topic.get("perf_views"),
        "perf_likes": topic.get("perf_likes"),
        "perf_collects": topic.get("perf_collects"),
        "perf_watch_rate": topic.get("perf_watch_rate"),
        "perf_favorite_rate": topic.get("perf_favorite_rate"),
        "perf_comments": topic.get("perf_comments"),
        "perf_shares": topic.get("perf_shares"),
        "creator_notes": topic.get("creator_notes"),
        "publish_match_terms": topic.get("publish_match_terms"),
        "review_status": topic.get("review_status"),
        "errors": _json_text(topic.get("errors") or []),
        "synced_at": _iso_now(),
        },
        _TOPIC_TEXT_FIELDS,
    )


def _frame_fields(topic: dict) -> dict[str, Any]:
    frame = topic.get("frame") or {}
    outline = frame.get("outline") or []
    return _coerce_text_fields(
        {
        _FRAMES_PRIMARY_FIELD: topic.get("title"),
        "topic_id": topic.get("topic_id"),
        "date": topic.get("date"),
        "platform_priority": topic.get("platform_priority"),
        "hook": frame.get("hook"),
        "outline": "\n".join(str(item) for item in outline),
        "cta": frame.get("cta"),
        "monetize_hook": frame.get("monetize_hook"),
        "platform_tips": frame.get("platform_tips"),
        "pipeline_run_id": topic.get("pipeline_run_id"),
        "model_version": topic.get("model_version"),
        "status": topic.get("status"),
        "errors": _json_text(topic.get("errors") or []),
        "synced_at": _iso_now(),
        },
        _FRAME_TEXT_FIELDS,
    )


def _coerce_text_fields(record: dict[str, Any], text_fields: set[str]) -> dict[str, Any]:
    coerced: dict[str, Any] = {}
    for field_name, value in record.items():
        if field_name in text_fields:
            coerced[field_name] = "" if value is None else str(value)
        else:
            coerced[field_name] = value
    return coerced


def build_sync_tasks(topics: list[dict]) -> list[dict]:
    tasks: list[dict] = []
    for topic in topics:
        if _topics_table_ready():
            tasks.append(
                {
                    "entity_type": "topic",
                    "entity_key": str(topic.get("topic_id")),
                    "table_name": "topics",
                    "payload": {"fields": _topic_fields(topic)},
                }
            )
        if _frames_table_ready() and topic.get("frame"):
            tasks.append(
                {
                    "entity_type": "frame",
                    "entity_key": str(topic.get("topic_id")),
                    "table_name": "content_frames",
                    "payload": {"fields": _frame_fields(topic)},
                }
            )
    return tasks


def _table_id(table_name: str) -> str | None:
    if table_name == "topics":
        return TOPICS_TABLE_ID
    if table_name == "content_frames":
        return FRAMES_TABLE_ID
    return None


async def _batch_create_records(client, table_name: str, payloads: list[dict]) -> None:
    table_id = _table_id(table_name)
    if not BITABLE_APP_TOKEN or not table_id:
        raise RuntimeError(f"Bitable table config missing for {table_name}")

    token = await get_tenant_access_token(client)
    url = (
        f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/"
        f"{BITABLE_APP_TOKEN}/tables/{table_id}/records/batch_create"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    for idx in range(0, len(payloads), _MAX_BATCH_SIZE):
        chunk = payloads[idx : idx + _MAX_BATCH_SIZE]
        resp = await request_with_retry(client, "POST", url, headers=headers, json={"records": chunk})
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"Bitable batch_create failed for {table_name}: "
                f"code={data.get('code')} msg={data.get('msg')}"
            )


async def sync_topics_to_bitable(client, topics: list[dict]) -> dict[str, Any]:
    result = {
        "enabled": bitable_sync_enabled(),
        "synced_topics": 0,
        "synced_frames": 0,
        "queued_tasks": [],
        "errors": [],
        "skipped_reason": None,
    }
    if not topics:
        return result
    if not bitable_sync_enabled():
        result["skipped_reason"] = "Bitable sync not configured yet"
        return result

    tasks = build_sync_tasks(topics)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for task in tasks:
        grouped[task["table_name"]].append(task)

    for table_name, table_tasks in grouped.items():
        try:
            payloads = [task["payload"] for task in table_tasks]
            await _batch_create_records(client, table_name, payloads)
            if table_name == "topics":
                result["synced_topics"] += len(table_tasks)
            elif table_name == "content_frames":
                result["synced_frames"] += len(table_tasks)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(str(exc))
            result["queued_tasks"].extend(table_tasks)

    return result


async def flush_bitable_outbox(client, limit: int = 100) -> dict[str, Any]:
    summary = {"processed": 0, "synced": 0, "failed": 0, "skipped": 0}
    if not bitable_sync_enabled():
        return summary

    async with AsyncSessionLocal() as session:
        tasks = await crud.list_bitable_sync_tasks(session, status="pending", limit=limit)
        if not tasks:
            return summary

        grouped: dict[str, list[Any]] = defaultdict(list)
        for task in tasks:
            grouped[task.table_name].append(task)

        for table_name, table_tasks in grouped.items():
            summary["processed"] += len(table_tasks)
            try:
                payloads = [json.loads(task.payload_json) for task in table_tasks]
                await _batch_create_records(client, table_name, payloads)
                await crud.mark_bitable_sync_tasks_done(session, [task.id for task in table_tasks])
                summary["synced"] += len(table_tasks)
            except Exception as exc:  # noqa: BLE001
                await crud.mark_bitable_sync_tasks_failed(
                    session,
                    [task.id for task in table_tasks],
                    str(exc),
                )
                summary["failed"] += len(table_tasks)

    return summary
