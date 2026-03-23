from __future__ import annotations

import re
from typing import Any

from config import BITABLE_APP_TOKEN, TOPICS_TABLE_ID, FEISHU_BASE_URL
from db import crud
from db.session import AsyncSessionLocal
from tools.feishu_auth import feishu_enabled, get_tenant_access_token
from pipeline.utils import request_with_retry

_FEEDBACK_FIELDS = (
    "publish_status",
    "publish_url",
    "publish_at",
    "perf_watch_rate",
    "perf_favorite_rate",
    "perf_comments",
    "perf_shares",
    "creator_notes",
    "publish_match_terms",
    "review_status",
)
_DOUYIN_ID_RE = re.compile(r"\b(\d{19})\b")


def feedback_sync_enabled() -> bool:
    return bool(feishu_enabled() and BITABLE_APP_TOKEN and TOPICS_TABLE_ID)


def _has_feedback(fields: dict[str, Any]) -> bool:
    return any(fields.get(name) not in (None, "", []) for name in _FEEDBACK_FIELDS)


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _normalize_feedback(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "publish_status": fields.get("publish_status") or None,
        "publish_url": fields.get("publish_url") or None,
        "publish_at": fields.get("publish_at") or None,
        "perf_watch_rate": _as_float(fields.get("perf_watch_rate")),
        "perf_favorite_rate": _as_float(fields.get("perf_favorite_rate")),
        "perf_comments": _as_int(fields.get("perf_comments")),
        "perf_shares": _as_int(fields.get("perf_shares")),
        "creator_notes": fields.get("creator_notes") or None,
        "publish_match_terms": fields.get("publish_match_terms") or None,
        "review_status": fields.get("review_status") or None,
    }


def _infer_feedback_platform(publish_url: str | None, fallback_platform: str | None) -> str | None:
    normalized_platform = str(fallback_platform or "").strip().lower()
    normalized_url = str(publish_url or "").strip().lower()
    if "douyin.com" in normalized_url:
        return "douyin"
    if "xiaohongshu.com" in normalized_url or "xhslink.com" in normalized_url:
        return "xiaohongshu"
    if "channels.weixin.qq.com" in normalized_url:
        return "shipinhao"
    if normalized_platform in {"douyin", "xiaohongshu", "shipinhao"}:
        return normalized_platform
    return None


def _extract_feedback_video_id(publish_url: str | None, platform: str | None) -> str | None:
    url = str(publish_url or "").strip()
    if not url:
        return None
    if platform == "douyin":
        match = _DOUYIN_ID_RE.search(url)
        return match.group(1) if match else None
    candidate = url.rstrip("/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9]", "", candidate)
    return cleaned or None


async def _list_topic_records(client) -> list[dict]:
    token = await get_tenant_access_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    records: list[dict] = []
    page_token: str | None = None

    while True:
        suffix = f"?page_size=500&page_token={page_token}" if page_token else "?page_size=500"
        url = (
            f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/"
            f"{BITABLE_APP_TOKEN}/tables/{TOPICS_TABLE_ID}/records{suffix}"
        )
        resp = await request_with_retry(client, "GET", url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"Feedback sync list records failed: code={data.get('code')} msg={data.get('msg')}"
            )
        payload = data.get("data") or {}
        records.extend(payload.get("items") or [])
        if not payload.get("has_more"):
            break
        page_token = payload.get("page_token")

    return records


async def sync_feedback_from_bitable(client) -> dict[str, Any]:
    summary = {
        "enabled": feedback_sync_enabled(),
        "processed": 0,
        "updated": 0,
        "missing_topics": [],
        "errors": [],
    }
    if not feedback_sync_enabled():
        summary["errors"].append("Feedback sync skipped: Bitable topics table not configured")
        return summary

    try:
        records = await _list_topic_records(client)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(str(exc))
        return summary

    async with AsyncSessionLocal() as session:
        for record in records:
            fields = record.get("fields") or {}
            topic_key = fields.get("topic_id")
            if not topic_key or not _has_feedback(fields):
                continue

            feedback = _normalize_feedback(fields)
            summary["processed"] += 1
            row = await crud.update_topic_feedback(session, topic_key, feedback)
            if not row:
                summary["missing_topics"].append(topic_key)
                continue

            platform = _infer_feedback_platform(feedback.get("publish_url"), row.platform_priority)
            if platform and feedback.get("publish_url"):
                await crud.upsert_platform_feedback(
                    session,
                    {
                        "topic_id": row.topic_id,
                        "platform": platform,
                        "video_id": _extract_feedback_video_id(feedback.get("publish_url"), platform),
                        "publish_url": feedback.get("publish_url"),
                        "status": feedback.get("publish_status") or "ok",
                        "comment_count": feedback.get("perf_comments"),
                        "share_count": feedback.get("perf_shares"),
                        "completion_rate": feedback.get("perf_watch_rate"),
                        "raw": {"source": "bitable_sync", "platform": platform},
                    },
                )

            metrics = {
                "feedback_watch_rate": feedback["perf_watch_rate"],
                "feedback_favorite_rate": feedback["perf_favorite_rate"],
                "feedback_comments": feedback["perf_comments"],
                "feedback_shares": feedback["perf_shares"],
            }
            await crud.replace_feedback_score_details(
                session,
                row.id,
                metrics,
                platform=row.platform_priority,
            )
            summary["updated"] += 1

    return summary
