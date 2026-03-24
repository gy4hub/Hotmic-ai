import json
import hashlib
import time
import asyncio
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from collections.abc import Iterable
from typing import Any
from config import (
    ANALYSIS_CACHE_ENABLED,
    ANALYSIS_CACHE_LOOKBACK_DAYS,
    ANALYZER_BATCH_CONCURRENCY,
    ANALYZER_BATCH_SIZE,
    ANALYZE_API_KEY,
    ANALYZE_BASE_URL,
    ANALYZE_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    GEMINI_API_KEY,
    GEMINI_FLASH_MODEL,
    PREFILTER_ENABLED,
    PREFILTER_MODEL,
    PREFILTER_THRESHOLD,
    QWEN_ANALYZE_TIMEOUT,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_MODEL,
    is_mock_mode,
)
from db import crud
from db.session import AsyncSessionLocal
from pipeline.editorial import build_editorial_prompt_section, normalize_editorial_item
from pipeline.types import TopicPayload, UsageSummary
from pipeline.utils import request_with_retry

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
ANALYZE_PROMPT_PATH = str(Path(__file__).resolve().parent.parent / "config" / "prompts" / "analyze_hotspot.txt")
PREFILTER_PROMPT_PATH = str(Path(__file__).resolve().parent.parent / "config" / "prompts" / "prefilter_topic.txt")
CLUSTER_DOMAIN_RULES: dict[str, tuple[str, ...]] = {
    "医保进院难": (
        "gov.cn",
        "nhsa.gov.cn",
        "cctv",
        "央视",
        "chinanews",
        "guancha",
        "news.cn",
        "cnr.cn",
        "people.com.cn",
    ),
    "司美格鲁肽灰市": (
        "nytimes",
        "rss_nyt_health",
        "statnews",
        "stat_pharma",
        "fda.gov",
        "fda_safety",
        "endocrine",
        "reuters",
    ),
    "药品安全警报": (
        "fda.gov",
        "fda_safety",
        "medwatch",
        "who.int",
        "who_alerts",
        "nmpa.gov.cn",
        "nmpa_news",
    ),
    "抗衰骗局": (
        "36kr",
        "rss_36kr",
        "huxiu",
        "rss_huxiu",
        "ifanr",
        "rss_ifanr",
        "geekpark",
        "rss_geekpark",
        "dxy",
        "rss_dxy",
    ),
}

_model_validated = False
_model_valid = False
_model_error: str | None = None
HIGH_EMOTION_HINTS = (
    "骗",
    "骗局",
    "风险",
    "警报",
    "曝光",
    "出事",
    "别",
    "误区",
    "难",
    "涨价",
    "黑幕",
)
HIGH_TIMELY_HINTS = (
    "今日",
    "刚刚",
    "最新",
    "通报",
    "发布",
    "点名",
    "曝光",
)


def _prompt_from_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _make_topic_id(title: str, url: str, suffix: str | None = None) -> str:
    raw = f"{title}|{url}".encode("utf-8")
    base = hashlib.sha1(raw).hexdigest()[:16]
    if suffix:
        return f"{base}_{suffix}"
    return base


def _clamp_score(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, numeric))


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _mock_scores(seed: str) -> dict[str, int]:
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16)
    return {
        "emotion": (h % 5) + 1,
        "timely": (h >> 3) % 5 + 1,
        "subvert": (h >> 6) % 5 + 1,
        "relate": (h >> 9) % 5 + 1,
        "spread": (h >> 12) % 5 + 1,
        "tension": (h >> 15) % 5 + 1,
        "depth": (h >> 18) % 5 + 1,
    }


async def _validate_model(ext_client) -> tuple[bool, str | None, bool]:
    global _model_validated, _model_valid, _model_error
    if _model_validated:
        return _model_valid, _model_error, False
    if not GEMINI_API_KEY:
        _model_validated = True
        _model_valid = False
        _model_error = "GEMINI_API_KEY missing"
        return _model_valid, _model_error, False

    url = f"{GEMINI_BASE}/models/{GEMINI_FLASH_MODEL}"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    try:
        resp = await request_with_retry(ext_client, "GET", url, headers=headers)
        if resp.status_code == 200:
            _model_valid = True
            _model_error = None
        else:
            _model_valid = False
            _model_error = f"Model validation failed: {resp.status_code} {resp.text}"
    except Exception as exc:  # noqa: BLE001
        _model_valid = False
        _model_error = f"Model validation exception: {exc}"
    _model_validated = True
    return _model_valid, _model_error, True


def _extract_items(parsed: object) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        return [item for item in parsed.get("items") if isinstance(item, dict)]
    return []


def _extract_prefilter_mapping(topics: list[TopicPayload], parsed_items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    topic_by_index = {idx: topic for idx, topic in enumerate(topics)}
    index_by_title = {
        _normalize_title(topic.get("title", "")): idx
        for idx, topic in enumerate(topics)
        if topic.get("title")
    }
    mapped_items: dict[int, dict[str, Any]] = {}
    used_indexes: set[int] = set()

    for fallback_index, item in enumerate(parsed_items):
        topic_index = item.get("input_index")
        if isinstance(topic_index, str) and topic_index.isdigit():
            topic_index = int(topic_index)
        if not isinstance(topic_index, int) or topic_index not in topic_by_index or topic_index in used_indexes:
            input_title = _normalize_title(item.get("input_title"))
            topic_index = index_by_title.get(input_title)
        if not isinstance(topic_index, int) or topic_index not in topic_by_index or topic_index in used_indexes:
            if fallback_index < len(topics):
                topic_index = fallback_index
        if isinstance(topic_index, int) and topic_index in topic_by_index and topic_index not in used_indexes:
            mapped_items[topic_index] = item
            used_indexes.add(topic_index)

    return mapped_items


def _normalize_title(text: str | None) -> str:
    return "".join((text or "").split()).strip().lower()


def _english_ratio(text: str | None) -> float:
    value = text or ""
    if not value:
        return 0.0
    english_chars = sum(1 for char in value if ("a" <= char.lower() <= "z"))
    return english_chars / max(len(value), 1)


def _should_use_localized_title(original_title: str, localized_title: str) -> bool:
    if not localized_title:
        return False
    if _english_ratio(original_title) > 0.4:
        return True

    normalized_original = (original_title or "").strip()
    normalized_localized = (localized_title or "").strip()
    if not normalized_original or not normalized_localized:
        return False
    if normalized_original == normalized_localized:
        return False

    weak_patterns = (
        "bug",
        "诚邀您一起探讨",
        "大会",
        "北京见",
        "未来发展",
        "pd-1",
        "彻底火了",
    )
    question_result_patterns = (
        "为什么",
        "什么时候",
        "不等于",
        "不是一下",
        "分几步",
    )

    original_lower = normalized_original.lower()
    localized_lower = normalized_localized.lower()
    if any(pattern in original_lower for pattern in weak_patterns):
        return True
    if any(pattern in localized_lower for pattern in question_result_patterns):
        return True
    if len(normalized_original) > 30 and len(normalized_localized) <= 28:
        return True
    return False


def _source_cluster_haystack(topic: TopicPayload) -> str:
    return " ".join(
        str(topic.get(key) or "").strip().lower()
        for key in ("url", "source", "original_title", "title")
    )


def _check_source_cluster_consistency(topic: TopicPayload) -> bool:
    cluster = str(topic.get("topic_cluster") or "").strip()
    expected_tokens = CLUSTER_DOMAIN_RULES.get(cluster)
    if not expected_tokens:
        return False
    haystack = _source_cluster_haystack(topic)
    return not any(token.lower() in haystack for token in expected_tokens)


def _build_results(topics: list[TopicPayload], parsed_items: list[dict[str, Any]]) -> list[TopicPayload]:
    topic_by_index = {idx: topic for idx, topic in enumerate(topics)}
    index_by_title = {
        _normalize_title(topic.get("title", "")): idx
        for idx, topic in enumerate(topics)
        if topic.get("title")
    }
    mapped_items: dict[int, dict[str, Any]] = {}
    used_indexes: set[int] = set()

    for fallback_index, item in enumerate(parsed_items):
        topic_index = item.get("input_index")
        if isinstance(topic_index, str) and topic_index.isdigit():
            topic_index = int(topic_index)
        if not isinstance(topic_index, int) or topic_index not in topic_by_index or topic_index in used_indexes:
            input_title = _normalize_title(item.get("input_title"))
            topic_index = index_by_title.get(input_title)
        if not isinstance(topic_index, int) or topic_index not in topic_by_index or topic_index in used_indexes:
            while fallback_index in used_indexes and fallback_index < len(topics):
                fallback_index += 1
            if fallback_index < len(topics):
                topic_index = fallback_index
        if isinstance(topic_index, int) and topic_index in topic_by_index and topic_index not in used_indexes:
            mapped_items[topic_index] = item
            used_indexes.add(topic_index)

    results: list[TopicPayload] = []
    for i, t in enumerate(topics):
        item = mapped_items.get(i, {})
        scores = item.get("scores", {})
        item_errors: list[str] = []
        original_title = str(t.get("title") or "").strip()
        echoed_title = item.get("input_title")
        if echoed_title and _normalize_title(echoed_title) != _normalize_title(original_title):
            item_errors.append("Analyzer returned mismatched input_title; result was realigned by topic index/title.")
        localized_title = (item.get("localized_title") or "").strip()
        final_title = original_title
        if _should_use_localized_title(original_title, localized_title):
            final_title = localized_title
        editorial_fields = normalize_editorial_item(
            {**t, "title": final_title},
            item,
        )
        cluster_mismatch = _check_source_cluster_consistency(
            {
                **t,
                "title": final_title,
                "original_title": original_title,
                "topic_cluster": editorial_fields.get("topic_cluster"),
            }
        )
        if cluster_mismatch:
            item_errors.append("Analyzer topic_cluster mismatches source/url signal; scorer penalty applied.")
        results.append(
            {
                **{k: v for k, v in t.items() if k != "_analysis_index"},
                "topic_id": _make_topic_id(t.get("title", ""), t.get("url", "")),
                "title": final_title,
                "original_title": original_title,
                "localized_title": localized_title,
                "summary": item.get("summary"),
                "keywords": item.get("keywords", []),
                "angle_type": item.get("angle_type"),
                "content_type": item.get("content_type"),
                "competitor_angle": item.get("competitor_angle"),
                "angle_gap": item.get("angle_gap"),
                **editorial_fields,
                "cluster_mismatch": cluster_mismatch,
                "scores": scores,
                "status": "ok",
                "errors": item_errors,
            }
        )
    return results


def _usage_summary(provider: str, model: str, endpoint: str, usage: dict[str, Any]) -> UsageSummary:
    prompt_tokens = (
        usage.get("prompt_tokens")
        or usage.get("promptTokenCount")
        or usage.get("promptTokens")
    )
    output_tokens = (
        usage.get("completion_tokens")
        or usage.get("candidatesTokenCount")
        or usage.get("outputTokens")
    )
    return {
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens,
    }


def _analysis_input_topic(topic: TopicPayload) -> dict[str, Any]:
    source_type = str(topic.get("source_type") or "").strip()
    if not source_type:
        source = str(topic.get("source") or "").strip().lower()
        if source == "evergreen":
            source_type = "evergreen"
        elif source.startswith("competitor_"):
            source_type = "competitor"
        else:
            source_type = "hotspot"
    return {
        "_analysis_index": topic.get("_analysis_index"),
        "title": (topic.get("title") or "")[:160],
        "url": topic.get("url"),
        "source": topic.get("source"),
        "source_type": source_type,
        "timestamp": topic.get("timestamp"),
        # Keep enough context for judgment, but cap payload size so Qwen doesn't stall.
        "raw_snippet": (topic.get("raw_snippet") or "")[:280],
    }


def _json_loads_maybe(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _parse_topic_timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = text.replace("Z", "+00:00").replace(" UTC", "+00:00")
    try:
        return float(int(cleaned))
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(cleaned).timestamp()
    except ValueError:
        return None


def _fast_timeliness_window(topic: TopicPayload) -> str:
    source_type = str(topic.get("source_type") or "").strip().lower()
    if source_type == "evergreen":
        return "evergreen"
    timestamp = _parse_topic_timestamp(topic.get("timestamp"))
    if timestamp is not None:
        age_seconds = max(time.time() - timestamp, 0)
        if age_seconds <= 3 * 24 * 3600:
            return "burst"
        if age_seconds <= 14 * 24 * 3600:
            return "slow_burn"
    text = " ".join(str(topic.get(key) or "") for key in ("title", "raw_snippet"))
    if any(hint in text for hint in HIGH_TIMELY_HINTS):
        return "burst"
    return "slow_burn"


def _fast_score_timely(topic: TopicPayload) -> int:
    window = _fast_timeliness_window(topic)
    if window == "evergreen":
        return 2
    if window == "burst":
        return 5
    return 3


def _fast_score_emotion(topic: TopicPayload) -> int:
    text = " ".join(str(topic.get(key) or "") for key in ("title", "raw_snippet"))
    hits = sum(1 for hint in HIGH_EMOTION_HINTS if hint in text)
    if hits >= 2:
        return 5
    if hits == 1:
        return 4
    if str(topic.get("source_type") or "").strip().lower() == "evergreen":
        return 3
    return 2


def _row_title_similarity(topic: TopicPayload, row: Any) -> float:
    source_title = str(topic.get("title") or "")
    candidates = [
        str(getattr(row, "title", "") or ""),
        str(getattr(row, "original_title", "") or ""),
        str(getattr(row, "localized_title", "") or ""),
    ]
    similarities = [_title_similarity(source_title, candidate) for candidate in candidates if candidate]
    return max(similarities) if similarities else 0.0


def _title_similarity(left: str, right: str) -> float:
    left_norm = _normalize_title(left)
    right_norm = _normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _match_cached_topic(topic: TopicPayload, recent_rows: list[Any]) -> Any | None:
    best_row = None
    best_score = 0.0
    for row in recent_rows:
        cluster = str(getattr(row, "topic_cluster", "") or "").strip()
        if not cluster:
            continue
        score = _row_title_similarity(topic, row)
        if score > best_score:
            best_score = score
            best_row = row
    if best_score >= 0.6:
        return best_row
    return None


def _cached_scores(topic: TopicPayload, row: Any) -> dict[str, Any]:
    return {
        "emotion": _fast_score_emotion(topic),
        "timely": _fast_score_timely(topic),
        "subvert": getattr(row, "score_subvert", None) or 3,
        "relate": getattr(row, "score_relate", None) or 3,
        "spread": getattr(row, "score_spread", None) or 3,
        "tension": getattr(row, "score_tension", None) or 3,
        "depth": getattr(row, "score_depth", None) or 3,
    }


def _build_cached_result(topic: TopicPayload, row: Any) -> TopicPayload:
    original_title = str(topic.get("title") or "").strip()
    localized_title = str(getattr(row, "localized_title", "") or "").strip()
    final_title = localized_title if _should_use_localized_title(original_title, localized_title) else original_title
    cluster_mismatch = _check_source_cluster_consistency(
        {
            **topic,
            "title": final_title,
            "original_title": original_title,
            "topic_cluster": getattr(row, "topic_cluster", None),
        }
    )
    keywords = _json_loads_maybe(getattr(row, "keywords", None))
    if not isinstance(keywords, list):
        keywords = []
    return {
        **topic,
        "topic_id": _make_topic_id(str(topic.get("title") or ""), str(topic.get("url") or "")),
        "title": final_title,
        "original_title": original_title,
        "localized_title": localized_title,
        "summary": getattr(row, "summary", None) or (str(topic.get("raw_snippet") or "")[:100]),
        "keywords": keywords,
        "angle_type": getattr(row, "angle_type", None),
        "content_type": getattr(row, "content_type", None),
        "competitor_angle": getattr(row, "competitor_angle", None),
        "angle_gap": getattr(row, "angle_gap", None),
        "topic_line_primary": getattr(row, "topic_line_primary", None),
        "topic_line_secondary": getattr(row, "topic_line_secondary", None),
        "line_confidence": getattr(row, "line_confidence", None),
        "content_role": getattr(row, "content_role", None),
        "creator_fit": getattr(row, "creator_fit", None),
        "li_jie_value": getattr(row, "li_jie_value", None),
        "zhang_auntie_value": getattr(row, "zhang_auntie_value", None),
        "audience_core": getattr(row, "audience_core", None),
        "compliance_risk": getattr(row, "compliance_risk", None),
        "actionability_risk": getattr(row, "actionability_risk", None),
        "topic_cluster": getattr(row, "topic_cluster", None),
        "cluster_mismatch": cluster_mismatch,
        "parent_topic_cluster": getattr(row, "parent_topic_cluster", None),
        "series_anchor_id": getattr(row, "series_anchor_id", None),
        "reject_type": getattr(row, "reject_type", None),
        "rejection_reason": getattr(row, "rejection_reason", None),
        "timeliness_window": _fast_timeliness_window(topic),
        "platform_fit": getattr(row, "platform_fit", None),
        "decision_impact_level": getattr(row, "decision_impact_level", None),
        "scores": _cached_scores(topic, row),
        "status": "ok",
        "errors": [],
    }


async def _load_cached_analysis_rows(topics: list[TopicPayload]) -> dict[int, Any]:
    if not ANALYSIS_CACHE_ENABLED or not topics:
        return {}
    async with AsyncSessionLocal() as session:
        recent_rows = await crud.get_recent_editorial_topics(
            session,
            since_days=ANALYSIS_CACHE_LOOKBACK_DAYS,
            limit=200,
        )
        matched_clusters: dict[int, str] = {}
        cached_rows: dict[int, Any] = {}
        for index, topic in enumerate(topics):
            matched = _match_cached_topic(topic, recent_rows)
            if matched is not None:
                cached_rows[index] = matched
        return cached_rows


def _mock_prefilter_score(topic: TopicPayload) -> float:
    text = " ".join(
        str(topic.get(key) or "").strip().lower()
        for key in ("title", "raw_snippet", "url", "source")
    )
    if any(keyword in text for keyword in ("医保", "用药", "药", "健康", "养老", "家庭")):
        return 0.85
    if _english_ratio(str(topic.get("title") or "")) > 0.5 and any(token in text for token in ("nytimes", "ozempic", "medical product alert")):
        return 0.2
    return 0.45


def _chunk_topics(topics: list[TopicPayload], batch_size: int) -> Iterable[list[TopicPayload]]:
    safe_batch_size = max(batch_size, 1)
    for start in range(0, len(topics), safe_batch_size):
        yield topics[start : start + safe_batch_size]


def _merge_usage(base: UsageSummary, extra: UsageSummary) -> UsageSummary:
    if not extra:
        return base
    if not base:
        return dict(extra)
    merged = dict(base)
    if extra.get("provider"):
        merged["provider"] = extra.get("provider")
    if extra.get("model"):
        merged["model"] = extra.get("model")
    if extra.get("endpoint"):
        merged["endpoint"] = extra.get("endpoint")
    merged["input_tokens"] = (merged.get("input_tokens") or 0) + (extra.get("input_tokens") or 0)
    merged["output_tokens"] = (merged.get("output_tokens") or 0) + (extra.get("output_tokens") or 0)
    return merged


def _describe_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    detail = repr(exc).strip()
    if detail:
        return detail
    return exc.__class__.__name__


async def _analyze_with_qwen(
    int_client,
    topics: list[TopicPayload],
) -> tuple[list[TopicPayload], list[str], UsageSummary]:
    errors: list[str] = []
    usage: UsageSummary = {}

    prompt = _prompt_from_file(ANALYZE_PROMPT_PATH)
    prompt += build_editorial_prompt_section()
    prompt += "\n\n请输出 JSON 对象，格式：{\"items\": [...]}。"
    analysis_topics = [_analysis_input_topic(topic) for topic in topics]

    payload = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "INPUT_TOPICS_JSON=\n" + json.dumps(analysis_topics, ensure_ascii=False),
            },
        ],
        "response_format": {"type": "json_object"},
    }

    url = f"{QWEN_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        resp = await request_with_retry(
            int_client,
            "POST",
            url,
            headers=headers,
            content=content,
            timeout=QWEN_ANALYZE_TIMEOUT,
            max_retries=0,
        )
        resp.raise_for_status()
        data = resp.json()
        usage = _usage_summary("qwen", QWEN_MODEL, "chat.completions", data.get("usage", {}))
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = json.loads(content)
        items = _extract_items(parsed)
        return _build_results(topics, items), errors, usage
    except Exception as exc:  # noqa: BLE001
        err = f"Qwen analyze failed: {_describe_exception(exc)}"
        errors.append(err)
        failed = []
        for t in topics:
            failed.append({**t, "status": "failed", "errors": [err]})
        return failed, errors, usage


def _resolve_compatible_llm_target(model: str | None) -> dict[str, str] | None:
    normalized = str(model or "").strip()
    if not normalized:
        return None
    if normalized.startswith("qwen-"):
        if not QWEN_API_KEY:
            return None
        return {
            "provider": "qwen",
            "model": normalized,
            "base_url": QWEN_BASE_URL.rstrip("/"),
            "api_key": QWEN_API_KEY,
        }
    if normalized.startswith("deepseek-"):
        if not DEEPSEEK_API_KEY:
            return None
        return {
            "provider": "deepseek",
            "model": normalized,
            "base_url": DEEPSEEK_BASE_URL.rstrip("/"),
            "api_key": DEEPSEEK_API_KEY,
        }
    if not ANALYZE_API_KEY:
        return None
    return {
        "provider": "openai-compatible",
        "model": normalized,
        "base_url": ANALYZE_BASE_URL.rstrip("/"),
        "api_key": ANALYZE_API_KEY,
    }


async def _call_compatible_json_completion(
    int_client,
    *,
    model: str,
    prompt: str,
    user_content: str,
) -> tuple[list[dict[str, Any]], UsageSummary]:
    target = _resolve_compatible_llm_target(model)
    if not target:
        raise RuntimeError(f"No API credentials configured for model: {model}")

    payload = {
        "model": target["model"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        "response_format": {"type": "json_object"},
    }
    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = await request_with_retry(
        int_client,
        "POST",
        f"{target['base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {target['api_key']}",
            "Content-Type": "application/json; charset=utf-8",
        },
        content=content,
        timeout=QWEN_ANALYZE_TIMEOUT,
        max_retries=0,
    )
    resp.raise_for_status()
    data = resp.json()
    raw_content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    parsed = json.loads(raw_content)
    return _extract_items(parsed), _usage_summary(target["provider"], target["model"], "chat.completions", data.get("usage", {}))


async def _analyze_with_llm(
    int_client,
    topics: list[TopicPayload],
) -> tuple[list[TopicPayload], list[str], UsageSummary]:
    errors: list[str] = []
    usage: UsageSummary = {}
    prompt = _prompt_from_file(ANALYZE_PROMPT_PATH)
    prompt += build_editorial_prompt_section()
    prompt += "\n\n请输出 JSON 对象，格式：{\"items\": [...]}。"
    analysis_topics = [_analysis_input_topic(topic) for topic in topics]

    try:
        items, usage = await _call_compatible_json_completion(
            int_client,
            model=ANALYZE_MODEL,
            prompt=prompt,
            user_content="INPUT_TOPICS_JSON=\n" + json.dumps(analysis_topics, ensure_ascii=False),
        )
        return _build_results(topics, items), errors, usage
    except Exception as exc:  # noqa: BLE001
        err = f"LLM analyze failed ({ANALYZE_MODEL}): {_describe_exception(exc)}"
        errors.append(err)
        failed = []
        for t in topics:
            failed.append({**t, "status": "failed", "errors": [err]})
        return failed, errors, usage


async def _analyze_with_gemini(
    ext_client,
    topics: list[TopicPayload],
) -> tuple[list[TopicPayload], list[str], UsageSummary]:
    errors: list[str] = []
    usage: UsageSummary = {}

    valid, model_error, did_validate = await _validate_model(ext_client)
    if not valid:
        err = model_error or "Model validation failed"
        errors.append(err)
        failed = []
        for t in topics:
            failed.append({**t, "status": "failed", "errors": [err]})
        return failed, errors, usage

    if did_validate:
        await asyncio.sleep(2)

    prompt = _prompt_from_file(ANALYZE_PROMPT_PATH)
    prompt += build_editorial_prompt_section()
    analysis_topics = [_analysis_input_topic(topic) for topic in topics]
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                        + "\n\nINPUT_TOPICS_JSON=\n"
                        + json.dumps(analysis_topics, ensure_ascii=False)
                    }
                ]
            }
        ],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    url = f"{GEMINI_BASE}/models/{GEMINI_FLASH_MODEL}:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    try:
        resp = await request_with_retry(ext_client, "POST", url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        usage = _usage_summary(
            "google",
            GEMINI_FLASH_MODEL,
            "generateContent",
            data.get("usageMetadata", {}),
        )
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        parsed = json.loads(text)
        items = _extract_items(parsed)
        return _build_results(topics, items), errors, usage
    except Exception as exc:  # noqa: BLE001
        err = f"Gemini analyze failed: {_describe_exception(exc)}"
        errors.append(err)
        failed = []
        for t in topics:
            failed.append({**t, "status": "failed", "errors": [err]})
        return failed, errors, usage


async def prefilter_topics(
    int_client,
    topics: list[TopicPayload],
) -> tuple[list[TopicPayload], list[str], UsageSummary]:
    errors: list[str] = []
    usage: UsageSummary = {}

    if not topics or not PREFILTER_ENABLED:
        return topics, errors, usage

    if is_mock_mode():
        filtered = [topic for topic in topics if _mock_prefilter_score(topic) >= PREFILTER_THRESHOLD]
        return filtered, errors, usage

    if not _resolve_compatible_llm_target(PREFILTER_MODEL):
        return topics, errors, usage

    prompt = _prompt_from_file(PREFILTER_PROMPT_PATH)
    prompt += "\n\n请输出 JSON 对象，格式：{\"items\": [...]}。"
    analysis_topics = [_analysis_input_topic(topic) for topic in topics]

    try:
        items, usage = await _call_compatible_json_completion(
            int_client,
            model=PREFILTER_MODEL,
            prompt=prompt,
            user_content="INPUT_TOPICS_JSON=\n" + json.dumps(analysis_topics, ensure_ascii=False),
        )
        mapping = _extract_prefilter_mapping(topics, items)
        if not mapping:
            return topics, errors, usage

        filtered: list[TopicPayload] = []
        for index, topic in enumerate(topics):
            decision = mapping.get(index)
            if not decision:
                filtered.append(topic)
                continue
            relevant = _boolish(decision.get("relevant"))
            score = _clamp_score(decision.get("score"))
            if relevant and score >= PREFILTER_THRESHOLD:
                filtered.append(topic)
        return filtered, errors, usage
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Prefilter failed: {_describe_exception(exc)}")
        return topics, errors, usage


async def analyze_topics(
    ext_client,
    int_client,
    topics: list[TopicPayload],
) -> tuple[list[TopicPayload], list[str], UsageSummary]:
    errors: list[str] = []
    usage: UsageSummary = {}

    if not topics:
        return [], errors, usage

    indexed_topics = [{**topic, "_analysis_index": idx} for idx, topic in enumerate(topics)]

    if is_mock_mode():
        results: list[TopicPayload] = []
        suffix = str(time.time_ns())
        for t in indexed_topics:
            seed = t.get("title", "") + t.get("url", "")
            results.append(
                {
                    **{k: v for k, v in t.items() if k != "_analysis_index"},
                    "topic_id": _make_topic_id(t.get("title", ""), t.get("url", ""), suffix=suffix),
                    "original_title": t.get("title", ""),
                    "localized_title": "",
                    "summary": "MOCK: 这是一个示例摘要，包含时效/情绪/关键词/带货相关性。",
                    "keywords": ["医保", "药价", "政策"],
                    "angle_type": "A",
                    "content_type": "policy",
                    "competitor_angle": "多数报道只讲结论，缺商业逻辑",
                    "angle_gap": "解释政策背后利益链条",
                    "topic_line_primary": "public_issue",
                    "topic_line_secondary": None,
                    "line_confidence": 0.8,
                    "content_role": "spread",
                    "audience_core": "family_decision_maker",
                    "compliance_risk": "low",
                    "actionability_risk": "low",
                    "topic_cluster": "医疗政策变化",
                    "cluster_mismatch": False,
                    "parent_topic_cluster": None,
                    "series_anchor_id": None,
                    "reject_type": "none",
                    "rejection_reason": None,
                    "timeliness_window": "burst",
                    "platform_fit": "both",
                    "decision_impact_level": "high",
                    "scores": _mock_scores(seed),
                    "status": "ok",
                    "errors": [],
                }
            )
        return results, errors, usage

    cached_rows = await _load_cached_analysis_rows(indexed_topics)
    cached_results = [
        _build_cached_result(indexed_topics[index], row)
        for index, row in sorted(cached_rows.items())
    ]
    uncached_topics = [
        topic
        for index, topic in enumerate(indexed_topics)
        if index not in cached_rows
    ]

    compatible_target = _resolve_compatible_llm_target(ANALYZE_MODEL)
    if compatible_target and uncached_topics:
        batches = list(_chunk_topics(uncached_topics, ANALYZER_BATCH_SIZE))
        semaphore = asyncio.Semaphore(max(ANALYZER_BATCH_CONCURRENCY, 1))

        async def _run_batch(idx: int, batch: list[TopicPayload]):
            async with semaphore:
                batch_results, batch_errors, batch_usage = await _analyze_with_llm(int_client, batch)
                wrapped_errors = [
                    f"Analyzer batch {idx}/{len(batches)} failed: {err}"
                    for err in batch_errors
                ]
                return batch_results, wrapped_errors, batch_usage

        batch_outputs = await asyncio.gather(
            *[_run_batch(idx, batch) for idx, batch in enumerate(batches, start=1)]
        )
        all_results: list[TopicPayload] = []
        all_errors: list[str] = []
        aggregated_usage: UsageSummary = {}
        for batch_results, batch_errors, batch_usage in batch_outputs:
            all_results.extend(batch_results)
            all_errors.extend(batch_errors)
            aggregated_usage = _merge_usage(aggregated_usage, batch_usage)
        all_results.extend(cached_results)
        all_results.sort(key=lambda item: item.get("_analysis_index", 0))
        normalized_results = [{k: v for k, v in item.items() if k != "_analysis_index"} for item in all_results]
        return normalized_results, all_errors, aggregated_usage
    if cached_results and not uncached_topics:
        cached_results.sort(key=lambda item: item.get("_analysis_index", 0))
        normalized_results = [{k: v for k, v in item.items() if k != "_analysis_index"} for item in cached_results]
        return normalized_results, errors, usage
    if compatible_target:
        uncached_results, uncached_errors, uncached_usage = await _analyze_with_llm(int_client, uncached_topics)
    else:
        uncached_results, uncached_errors, uncached_usage = await _analyze_with_gemini(ext_client, uncached_topics)

    combined = uncached_results + cached_results
    combined.sort(key=lambda item: item.get("_analysis_index", 0))
    normalized_results = [{k: v for k, v in item.items() if k != "_analysis_index"} for item in combined]
    return normalized_results, uncached_errors, uncached_usage
