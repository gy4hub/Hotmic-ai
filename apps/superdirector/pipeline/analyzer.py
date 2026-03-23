import json
import hashlib
import time
import asyncio
from pathlib import Path
from collections.abc import Iterable
from typing import Any
from config import (
    ANALYZER_BATCH_CONCURRENCY,
    ANALYZER_BATCH_SIZE,
    GEMINI_API_KEY,
    GEMINI_FLASH_MODEL,
    QWEN_ANALYZE_TIMEOUT,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_MODEL,
    is_mock_mode,
)
from pipeline.editorial import build_editorial_prompt_section, normalize_editorial_item
from pipeline.types import TopicPayload, UsageSummary
from pipeline.utils import request_with_retry

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
ANALYZE_PROMPT_PATH = str(Path(__file__).resolve().parent.parent / "config" / "prompts" / "analyze_hotspot.txt")

_model_validated = False
_model_valid = False
_model_error: str | None = None


def _prompt_from_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _make_topic_id(title: str, url: str, suffix: str | None = None) -> str:
    raw = f"{title}|{url}".encode("utf-8")
    base = hashlib.sha1(raw).hexdigest()[:16]
    if suffix:
        return f"{base}_{suffix}"
    return base


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


def _rewrite_title_for_house_style(title: str, summary: str | None, keywords: list[str] | None) -> str:
    original = (title or "").strip()
    text = " ".join([original, summary or "", " ".join(keywords or [])]).lower()
    if not original:
        return original

    if ("医保" in text and ("开不出来" in text or "进院难" in text or "pd-1" in text or "bug" in text)):
        return "进了医保，为什么医院还是开不出来？"

    if "外泌体" in text and "315" in text:
        return "315点名外泌体：听起来像高科技，为什么反而最该警惕？"

    if "私域" in text and ("老人" in text or "养老金" in text or "健康讲座" in text):
        return "私域健康讲座为什么最容易掏空老人的养老金？"

    return original


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
        echoed_title = item.get("input_title")
        if echoed_title and _normalize_title(echoed_title) != _normalize_title(t.get("title", "")):
            item_errors.append("Analyzer returned mismatched input_title; result was realigned by topic index/title.")
        localized_title = (item.get("localized_title") or "").strip()
        final_title = t.get("title", "")
        if _should_use_localized_title(final_title, localized_title):
            final_title = localized_title
        final_title = _rewrite_title_for_house_style(
            final_title,
            item.get("summary"),
            item.get("keywords") or [],
        )
        editorial_fields = normalize_editorial_item(
            {**t, "title": final_title},
            item,
        )
        results.append(
            {
                **{k: v for k, v in t.items() if k != "_analysis_index"},
                "topic_id": _make_topic_id(t.get("title", ""), t.get("url", "")),
                "title": final_title,
                "summary": item.get("summary"),
                "keywords": item.get("keywords", []),
                "angle_type": item.get("angle_type"),
                "content_type": item.get("content_type"),
                "competitor_angle": item.get("competitor_angle"),
                "angle_gap": item.get("angle_gap"),
                **editorial_fields,
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
    return {
        "_analysis_index": topic.get("_analysis_index"),
        "title": (topic.get("title") or "")[:160],
        "url": topic.get("url"),
        "source": topic.get("source"),
        "timestamp": topic.get("timestamp"),
        # Keep enough context for judgment, but cap payload size so Qwen doesn't stall.
        "raw_snippet": (topic.get("raw_snippet") or "")[:280],
    }


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
        err = f"Gemini analyze failed: {exc}"
        errors.append(err)
        failed = []
        for t in topics:
            failed.append({**t, "status": "failed", "errors": [err]})
        return failed, errors, usage


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

    if QWEN_API_KEY:
        batches = list(_chunk_topics(indexed_topics, ANALYZER_BATCH_SIZE))
        semaphore = asyncio.Semaphore(max(ANALYZER_BATCH_CONCURRENCY, 1))

        async def _run_batch(idx: int, batch: list[TopicPayload]):
            async with semaphore:
                batch_results, batch_errors, batch_usage = await _analyze_with_qwen(int_client, batch)
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
        all_results.sort(key=lambda item: item.get("_analysis_index", 0))
        normalized_results = [{k: v for k, v in item.items() if k != "_analysis_index"} for item in all_results]
        return normalized_results, all_errors, aggregated_usage
    return await _analyze_with_gemini(ext_client, indexed_topics)
