from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from config import BITABLE_APP_TOKEN, FEISHU_BASE_URL, TOPICS_TABLE_ID
from db import crud
from db.session import AsyncSessionLocal
from pipeline.collector import _latest_mediacrawler_file
from pipeline.utils import request_with_retry
from tools.feishu_auth import feishu_enabled, get_tenant_access_token
from tools.telegram_sender import send_casey_message

DOUYIN_COOKIE_PATH = Path("/home/gchyang/.openclaw/superdirector/.douyin_cookie")
DOUYIN_WORK_LIST_URL = "https://creator.douyin.com/janus/douyin/creator/pc/work_list"
DOUYIN_REFERER = "https://creator.douyin.com/creator-micro/content/manage"
DOUYIN_WORK_LIST_PAGE_SIZE = 20
DOUYIN_WORK_LIST_MAX_PAGES = 3
MATCH_SCORE_THRESHOLD = 0.42
_DETAIL_ID_RE = re.compile(r"\b(\d{19})\b")
_XHS_NOTE_ID_RE = re.compile(r"/(?:explore|discovery/item|note)/([A-Za-z0-9]+)")
_COOKIE_EXPIRED_MARKERS = ("403", "401", "cookie", "登录", "status_code")


def feedback_manual_fill_link() -> str | None:
    if not (BITABLE_APP_TOKEN and TOPICS_TABLE_ID):
        return None
    return f"https://wcnlpn0avt8q.feishu.cn/base/{BITABLE_APP_TOKEN}?table={TOPICS_TABLE_ID}"


def _cookie_pairs_from_json(data: Any) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                name = item.get("name")
                value = item.get("value")
                if name and value is not None:
                    pairs.append((str(name), str(value)))
    elif isinstance(data, dict):
        if isinstance(data.get("cookies"), list):
            pairs.extend(_cookie_pairs_from_json(data["cookies"]))
        elif all(key in data for key in ("name", "value")):
            pairs.append((str(data["name"]), str(data["value"])))
    return pairs


def normalize_douyin_cookie(cookie_text: str) -> str:
    raw = (cookie_text or "").strip()
    if not raw:
        return ""

    path = Path(raw)
    if path.exists() and path.is_file():
        raw = path.read_text(encoding="utf-8").strip()

    if raw.startswith("[") or raw.startswith("{"):
        try:
            pairs = _cookie_pairs_from_json(json.loads(raw))
        except Exception:  # noqa: BLE001
            pairs = []
        if pairs:
            return "; ".join(f"{name}={value}" for name, value in pairs)

    return raw


def douyin_cookie_exists() -> bool:
    return DOUYIN_COOKIE_PATH.exists() and bool(load_douyin_cookie())


def load_douyin_cookie() -> str:
    if not DOUYIN_COOKIE_PATH.exists():
        return ""
    raw = DOUYIN_COOKIE_PATH.read_text(encoding="utf-8").strip()
    normalized = normalize_douyin_cookie(raw)
    if normalized and normalized != raw:
        DOUYIN_COOKIE_PATH.write_text(normalized, encoding="utf-8")
        DOUYIN_COOKIE_PATH.chmod(0o600)
    return normalized


def save_douyin_cookie(cookie_text: str) -> Path:
    normalized = normalize_douyin_cookie(cookie_text)
    if not normalized:
        raise ValueError("cookie is required")
    DOUYIN_COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOUYIN_COOKIE_PATH.write_text(normalized, encoding="utf-8")
    DOUYIN_COOKIE_PATH.chmod(0o600)
    return DOUYIN_COOKIE_PATH


def _extract_video_id(url: str) -> str | None:
    match = _DETAIL_ID_RE.search(url or "")
    return match.group(1) if match else None


def _extract_xhs_note_id(url: str) -> str | None:
    if not url:
        return None
    match = _XHS_NOTE_ID_RE.search(url)
    if match:
        return match.group(1)
    candidate = url.rstrip("/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9]", "", candidate)
    if len(cleaned) >= 6:
        return cleaned
    return None


def _status_from_error(text: str) -> str:
    lower = text.lower()
    if any(marker in lower for marker in _COOKIE_EXPIRED_MARKERS):
        return "cookie_expired"
    return "error"


def _normalize_title(text: str | None) -> str:
    cleaned = re.sub(r"#\S+", " ", text or "")
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "", cleaned)
    return cleaned.lower().strip()


def _topic_matching_texts(topic: Any) -> list[str]:
    values: list[str] = []
    if getattr(topic, "title", None):
        values.append(str(topic.title))

    raw_terms = getattr(topic, "publish_match_terms", None)
    if raw_terms:
        for part in re.split(r"[\n,，;；|]+", str(raw_terms)):
            part = part.strip()
            if part:
                values.append(part)

    raw_keywords = getattr(topic, "keywords", None)
    if raw_keywords:
        parsed: Any = raw_keywords
        if isinstance(raw_keywords, str):
            try:
                parsed = json.loads(raw_keywords)
            except Exception:  # noqa: BLE001
                parsed = raw_keywords
        if isinstance(parsed, list):
            values.extend(str(item).strip() for item in parsed if str(item).strip())
        elif isinstance(parsed, str) and parsed.strip():
            values.extend(part.strip() for part in re.split(r"[\n,，;；|]+", parsed) if part.strip())

    deduped: list[str] = []
    seen = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _topic_match_score(topic_title: str, video_title: str) -> float:
    left = _normalize_title(topic_title)
    right = _normalize_title(video_title)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    prefix_bonus = 0.0
    if left[:10] and right.startswith(left[:10]):
        prefix_bonus = 0.25
    elif right[:10] and left.startswith(right[:10]):
        prefix_bonus = 0.2
    contains_bonus = 0.15 if left in right or right in left else 0.0
    ratio = SequenceMatcher(None, left[:40], right[:40]).ratio()
    return min(1.0, ratio + prefix_bonus + contains_bonus)


def _iso_from_ts(value: Any) -> str | None:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat().replace("+00:00", "Z")


def _collect_rate(collect_count: int, play_count: int) -> float | None:
    if play_count <= 0:
        return None
    return round(collect_count / play_count, 6)


def _douyin_headers(cookie: str) -> dict[str, str]:
    return {
        "Cookie": cookie,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://creator.douyin.com",
        "Referer": DOUYIN_REFERER,
        "x-secsdk-csrf-request": "1",
        "x-secsdk-csrf-version": "1.2.22",
    }


async def _fetch_work_list_page(client, cookie: str, *, max_cursor: int) -> dict[str, Any]:
    resp = await request_with_retry(
        client,
        "GET",
        DOUYIN_WORK_LIST_URL,
        headers=_douyin_headers(cookie),
        params={
            "status": 0,
            "count": DOUYIN_WORK_LIST_PAGE_SIZE,
            "max_cursor": max_cursor,
            "scene": "star_atlas",
            "device_platform": "android",
            "aid": 1128,
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    status_code = int(payload.get("status_code") or 0)
    if status_code != 0:
        raise RuntimeError(
            f"creator work_list returned status_code={status_code}: {json.dumps(payload, ensure_ascii=False)[:400]}"
        )
    return payload


async def _fetch_creator_work_list(client, cookie: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    max_cursor = 0
    for page_index in range(DOUYIN_WORK_LIST_MAX_PAGES):
        if page_index:
            await asyncio.sleep(3)
        payload = await _fetch_work_list_page(client, cookie, max_cursor=max_cursor)
        aweme_list = payload.get("aweme_list") or []
        items.extend(aweme_list)
        if not payload.get("has_more"):
            break
        try:
            max_cursor = int(payload.get("max_cursor") or 0)
        except (TypeError, ValueError):
            break
    return items


def _extract_video_title(item: dict[str, Any]) -> str:
    return (
        str(item.get("desc") or "").strip()
        or str(item.get("item_title") or "").strip()
        or str(((item.get("share_info") or {}).get("share_desc")) or "").strip()
    )


def _build_video_record(item: dict[str, Any]) -> dict[str, Any]:
    stats = item.get("statistics") or {}
    video_id = str(item.get("aweme_id") or item.get("item_id") or "")
    play_count = int(stats.get("play_count") or 0)
    collect_count = int(stats.get("collect_count") or 0)
    return {
        "video_id": video_id,
        "title": _extract_video_title(item),
        "publish_url": f"https://www.douyin.com/video/{video_id}" if video_id else "",
        "publish_at": _iso_from_ts(item.get("create_time")),
        "play_count": play_count,
        "digg_count": int(stats.get("digg_count") or 0),
        "comment_count": int(stats.get("comment_count") or 0),
        "collect_count": collect_count,
        "share_count": int(stats.get("share_count") or 0),
        "collect_rate": _collect_rate(collect_count, play_count),
        "raw": item,
    }


def _match_platform_item_to_topic(
    item: dict[str, Any],
    topics: list[Any],
    *,
    used_topic_ids: set[str],
    item_content_id: str | None,
    topic_url_id_extractor,
) -> tuple[Any | None, float]:
    for topic in topics:
        if item_content_id and topic_url_id_extractor(getattr(topic, "publish_url", "") or "") == item_content_id:
            return topic, 1.0

    best_topic = None
    best_score = 0.0
    for topic in topics:
        if topic.topic_id in used_topic_ids:
            continue
        topic_publish_url = getattr(topic, "publish_url", "") or ""
        topic_content_id = topic_url_id_extractor(topic_publish_url)
        if topic_publish_url and item_content_id and topic_content_id not in (None, item_content_id):
            continue
        score = max(
            (_topic_match_score(candidate, item["title"]) for candidate in _topic_matching_texts(topic)),
            default=0.0,
        )
        if score > best_score:
            best_topic = topic
            best_score = score
    if best_score < MATCH_SCORE_THRESHOLD:
        return None, best_score
    return best_topic, best_score


def _match_work_item_to_topic(
    item: dict[str, Any],
    topics: list[Any],
    *,
    used_topic_ids: set[str],
) -> tuple[Any | None, float]:
    return _match_platform_item_to_topic(
        item,
        topics,
        used_topic_ids=used_topic_ids,
        item_content_id=item.get("video_id"),
        topic_url_id_extractor=_extract_video_id,
    )


def _build_xhs_record(item: dict[str, Any]) -> dict[str, Any]:
    note_url = str(item.get("note_url") or item.get("url") or "").strip()
    note_id = str(item.get("note_id") or _extract_xhs_note_id(note_url) or "")
    like_count = int(float(item.get("liked_count") or 0))
    collect_count = int(float(item.get("collected_count") or 0))
    comment_count = int(float(item.get("comment_count") or 0))
    share_count = int(float(item.get("share_count") or 0))
    view_count = item.get("view_count") or item.get("play_count") or item.get("note_view_count")
    try:
        play_count = int(float(view_count)) if view_count not in (None, "") else None
    except (TypeError, ValueError):
        play_count = None
    return {
        "note_id": note_id,
        "title": str(item.get("title") or item.get("desc") or "").strip(),
        "publish_url": note_url,
        "publish_at": _iso_from_ts(item.get("create_time")),
        "play_count": play_count,
        "digg_count": like_count,
        "comment_count": comment_count,
        "collect_count": collect_count,
        "share_count": share_count,
        "collect_rate": _collect_rate(collect_count, play_count or 0) if play_count else None,
        "raw": item,
    }


def _load_xhs_records(limit: int = 50) -> tuple[list[dict[str, Any]], str | None]:
    latest = _latest_mediacrawler_file(["xhs", "xiaohongshu", "rednote"])
    if not latest:
        return [], None
    try:
        raw = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return [], str(latest)

    records: list[dict[str, Any]] = []
    for entry in raw[:limit] if isinstance(raw, list) else []:
        record = _build_xhs_record(entry)
        if record["title"] and record["publish_url"]:
            records.append(record)
    return records, str(latest)


async def collect_xhs_feedback(client) -> dict[str, Any]:
    records, latest_path = _load_xhs_records()
    summary: dict[str, Any] = {
        "status": "ok",
        "discovered_notes": len(records),
        "matched_topics": 0,
        "updated_topics": 0,
        "unmatched_notes": [],
        "errors": [],
        "items": [],
        "latest_file": latest_path,
        "manual_fill_link": feedback_manual_fill_link(),
    }

    if not latest_path:
        summary["status"] = "skipped"
        summary["errors"].append("No Xiaohongshu MediaCrawler export found")
        return summary

    if not records:
        summary["status"] = "skipped"
        summary["errors"].append("Xiaohongshu MediaCrawler export contained no usable notes")
        return summary

    async with AsyncSessionLocal() as session:
        topics = await crud.list_topics_for_publish_matching(session, platform="xiaohongshu", limit=200)

    if not topics:
        summary["status"] = "skipped"
        summary["errors"].append("No Xiaohongshu topics available for matching")
        return summary

    used_topic_ids: set[str] = set()
    bitable_updates: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        for item in records:
            topic, score = _match_platform_item_to_topic(
                item,
                topics,
                used_topic_ids=used_topic_ids,
                item_content_id=item.get("note_id"),
                topic_url_id_extractor=_extract_xhs_note_id,
            )
            if topic is None:
                summary["unmatched_notes"].append(
                    {
                        "note_id": item["note_id"],
                        "title": item["title"],
                        "match_score": round(score, 3),
                    }
                )
                continue

            used_topic_ids.add(topic.topic_id)
            feedback_payload = {
                "topic_id": topic.topic_id,
                "platform": "xiaohongshu",
                "video_id": item["note_id"],
                "publish_url": item["publish_url"],
                "status": "ok",
                "play_count": item["play_count"],
                "digg_count": item["digg_count"],
                "comment_count": item["comment_count"],
                "collect_count": item["collect_count"],
                "share_count": item["share_count"],
                "raw": item["raw"],
            }
            await crud.upsert_platform_feedback(session, feedback_payload)
            topic_update = {
                "publish_status": "published",
                "publish_url": item["publish_url"],
                "publish_at": item["publish_at"],
                "perf_likes": item["digg_count"],
                "perf_collects": item["collect_count"],
                "perf_favorite_rate": item["collect_rate"],
                "perf_comments": item["comment_count"],
                "perf_shares": item["share_count"],
            }
            if item["play_count"] is not None:
                topic_update["perf_views"] = item["play_count"]
            await crud.update_topic_feedback(session, topic.topic_id, topic_update)
            summary["matched_topics"] += 1
            summary["updated_topics"] += 1
            summary["items"].append(
                {
                    "topic_id": topic.topic_id,
                    "title": topic.title,
                    "note_id": item["note_id"],
                    "publish_url": item["publish_url"],
                    "match_score": round(score, 3),
                    "play_count": item["play_count"],
                    "digg_count": item["digg_count"],
                    "collect_count": item["collect_count"],
                    "comment_count": item["comment_count"],
                    "share_count": item["share_count"],
                }
            )
            bitable_update = {
                "topic_id": topic.topic_id,
                "publish_status": "published",
                "publish_url": item["publish_url"],
                "publish_at": item["publish_at"],
                "perf_likes": item["digg_count"],
                "perf_collects": item["collect_count"],
                "perf_favorite_rate": item["collect_rate"],
                "perf_comments": item["comment_count"],
                "perf_shares": item["share_count"],
            }
            if item["play_count"] is not None:
                bitable_update["perf_views"] = item["play_count"]
            bitable_updates.append(bitable_update)

    if bitable_updates:
        bitable_result = await _upsert_bitable_feedback(client, bitable_updates)
        summary["bitable_updated"] = bitable_result["updated"]
        summary["errors"].extend(bitable_result["errors"])
    else:
        summary["bitable_updated"] = 0

    if summary["matched_topics"] == 0 and summary["status"] == "ok":
        summary["status"] = "skipped"
    return summary


async def _upsert_bitable_feedback(client, updates: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {"updated": 0, "errors": []}
    if not (feishu_enabled() and BITABLE_APP_TOKEN and TOPICS_TABLE_ID and updates):
        return summary

    token = await get_tenant_access_token(client)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    list_url = (
        f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{TOPICS_TABLE_ID}/records?page_size=500"
    )
    resp = await request_with_retry(client, "GET", list_url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    items = ((data.get("data") or {}).get("items") or [])
    record_ids = {
        str((item.get("fields") or {}).get("topic_id")): item.get("record_id")
        for item in items
        if (item.get("fields") or {}).get("topic_id")
    }
    records = []
    for update in updates:
        record_id = record_ids.get(update["topic_id"])
        if not record_id:
            continue
        records.append(
            {
                "record_id": record_id,
                "fields": {
                    "publish_status": update.get("publish_status"),
                    "publish_url": update.get("publish_url"),
                    "publish_at": update.get("publish_at"),
                    "perf_views": update.get("perf_views"),
                    "perf_likes": update.get("perf_likes"),
                    "perf_collects": update.get("perf_collects"),
                    "perf_favorite_rate": update.get("perf_favorite_rate"),
                    "perf_comments": update.get("perf_comments"),
                    "perf_shares": update.get("perf_shares"),
                },
            }
        )
    if not records:
        return summary

    update_url = f"{FEISHU_BASE_URL}/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{TOPICS_TABLE_ID}/records/batch_update"
    resp = await request_with_retry(client, "POST", update_url, headers=headers, json={"records": records})
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        summary["errors"].append(
            f"Feedback bitable update failed: code={payload.get('code')} msg={payload.get('msg')}"
        )
        return summary
    summary["updated"] = len(records)
    return summary


async def collect_douyin_feedback(client) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": "ok",
        "cookie_configured": douyin_cookie_exists(),
        "discovered_videos": 0,
        "matched_topics": 0,
        "updated_topics": 0,
        "needs_manual_completion": 0,
        "unmatched_videos": [],
        "errors": [],
        "items": [],
        "manual_fill_link": feedback_manual_fill_link(),
    }

    if not douyin_cookie_exists():
        summary["status"] = "skipped"
        summary["errors"].append("Douyin cookie not configured")
        return summary

    cookie = load_douyin_cookie()
    try:
        videos = [_build_video_record(item) for item in await _fetch_creator_work_list(client, cookie)]
    except Exception as exc:  # noqa: BLE001
        error_text = str(exc)
        summary["status"] = "failed"
        summary["errors"].append(error_text)
        if _status_from_error(error_text) == "cookie_expired":
            await send_casey_message(
                client,
                "Casey 提醒：抖音 Cookie 可能已失效，创作者后台 work_list 接口返回异常。请执行 `/sd douyin-login` 更新 Cookie。",
            )
        return summary

    summary["discovered_videos"] = len(videos)
    if not videos:
        summary["status"] = "skipped"
        summary["errors"].append("No published Douyin videos found in creator backend")
        return summary

    async with AsyncSessionLocal() as session:
        topics = await crud.list_topics_for_publish_matching(session, platform="douyin", limit=200)

    if not topics:
        summary["status"] = "skipped"
        summary["errors"].append("No Douyin topics available for matching")
        return summary

    used_topic_ids: set[str] = set()
    bitable_updates: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        for item in videos:
            topic, score = _match_work_item_to_topic(item, topics, used_topic_ids=used_topic_ids)
            if topic is None:
                summary["unmatched_videos"].append(
                    {
                        "video_id": item["video_id"],
                        "title": item["title"],
                        "match_score": round(score, 3),
                    }
                )
                continue

            used_topic_ids.add(topic.topic_id)
            feedback_payload = {
                "topic_id": topic.topic_id,
                "platform": "douyin",
                "video_id": item["video_id"],
                "publish_url": item["publish_url"],
                "status": "ok",
                "play_count": item["play_count"],
                "digg_count": item["digg_count"],
                "comment_count": item["comment_count"],
                "collect_count": item["collect_count"],
                "share_count": item["share_count"],
                "raw": item["raw"],
            }
            await crud.upsert_platform_feedback(session, feedback_payload)
            await crud.update_topic_feedback(
                session,
                topic.topic_id,
                {
                    "publish_status": "published",
                    "publish_url": item["publish_url"],
                    "publish_at": item["publish_at"],
                    "perf_views": item["play_count"],
                    "perf_likes": item["digg_count"],
                    "perf_collects": item["collect_count"],
                    "perf_favorite_rate": item["collect_rate"],
                    "perf_comments": item["comment_count"],
                    "perf_shares": item["share_count"],
                },
            )
            summary["matched_topics"] += 1
            summary["updated_topics"] += 1
            if topic.perf_watch_rate in (None, 0):
                summary["needs_manual_completion"] += 1
            summary["items"].append(
                {
                    "topic_id": topic.topic_id,
                    "title": topic.title,
                    "video_id": item["video_id"],
                    "publish_url": item["publish_url"],
                    "match_score": round(score, 3),
                    "play_count": item["play_count"],
                    "digg_count": item["digg_count"],
                    "collect_count": item["collect_count"],
                    "comment_count": item["comment_count"],
                    "share_count": item["share_count"],
                    "collect_rate": item["collect_rate"],
                }
            )
            bitable_updates.append(
                {
                    "topic_id": topic.topic_id,
                    "publish_status": "published",
                    "publish_url": item["publish_url"],
                    "publish_at": item["publish_at"],
                    "perf_views": item["play_count"],
                    "perf_likes": item["digg_count"],
                    "perf_collects": item["collect_count"],
                    "perf_favorite_rate": item["collect_rate"],
                    "perf_comments": item["comment_count"],
                    "perf_shares": item["share_count"],
                }
            )

    if bitable_updates:
        bitable_result = await _upsert_bitable_feedback(client, bitable_updates)
        summary["bitable_updated"] = bitable_result["updated"]
        summary["errors"].extend(bitable_result["errors"])
    else:
        summary["bitable_updated"] = 0

    if summary["matched_topics"] == 0 and summary["status"] == "ok":
        summary["status"] = "skipped"
    return summary


async def feedback_status_summary() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        platforms: dict[str, dict[str, Any]] = {}
        for platform in ("douyin", "shipinhao", "xiaohongshu"):
            rows = await crud.list_platform_feedback(session, platform=platform, limit=50)
            topic_watch_rates = {}
            for row in rows:
                topic = await crud.get_topic_by_topic_id(session, row.topic_id)
                topic_watch_rates[row.topic_id] = topic.perf_watch_rate if topic else None
            tracked_topics = await crud.list_topics_for_publish_matching(session, platform=platform, limit=200)
            published_topics = [
                topic
                for topic in tracked_topics
                if any(getattr(topic, field, None) not in (None, "") for field in ("publish_status", "publish_url", "publish_at"))
            ]
            auto_collected = sum(1 for row in rows if row.status == "ok")
            needs_manual_completion = sum(
                1
                for row in rows
                if row.status == "ok" and topic_watch_rates.get(row.topic_id) in (None, 0)
            )
            platform_summary = {
                "auto_collected": auto_collected,
                "needs_manual_completion": needs_manual_completion,
                "tracked_topics": len(tracked_topics),
                "published_topics": len(published_topics),
                "missing_feedback_topics": max(len(published_topics) - auto_collected, 0),
                "items": [
                    {
                        "topic_id": row.topic_id,
                        "video_id": row.video_id,
                        "status": row.status,
                        "play_count": row.play_count,
                        "digg_count": row.digg_count,
                        "collect_count": row.collect_count,
                        "comment_count": row.comment_count,
                        "share_count": row.share_count,
                        "completion_rate": topic_watch_rates.get(row.topic_id),
                        "updated_at": row.updated_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
                        if row.updated_at
                        else None,
                        "error_message": row.error_message,
                    }
                    for row in rows
                ],
            }
            if platform == "douyin":
                platform_summary["cookie_configured"] = douyin_cookie_exists()
            platforms[platform] = platform_summary

    recommendations: list[str] = []
    if not platforms["douyin"].get("cookie_configured"):
        recommendations.append("抖音：先执行 /sd douyin-login 更新 Cookie，再运行 /feedback/collect?platform=douyin。")
    elif platforms["douyin"]["needs_manual_completion"] > 0:
        recommendations.append("抖音：已自动回收基础互动数据，但仍有完播率缺失，建议去 Bitable 补填后执行 /feedback/sync。")

    if platforms["shipinhao"]["published_topics"] > 0 and platforms["shipinhao"]["auto_collected"] == 0:
        recommendations.append("视频号：当前走手动方案，请在 Bitable 填写发布数据后执行 /feedback/sync。")

    if platforms["xiaohongshu"]["published_topics"] > 0 and platforms["xiaohongshu"]["auto_collected"] == 0:
        recommendations.append("小红书：确认 MediaCrawler 已产出 xhs 数据后，执行 /feedback/collect?platform=xiaohongshu。")

    douyin = platforms["douyin"]
    return {
        "cookie_configured": douyin.get("cookie_configured", False),
        "auto_collected": douyin["auto_collected"],
        "needs_manual_completion": douyin["needs_manual_completion"],
        "manual_fill_link": feedback_manual_fill_link(),
        "items": douyin["items"],
        "platforms": platforms,
        "recommendations": recommendations,
    }
