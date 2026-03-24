from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from config import ANALYZE_MODEL, BAIDU_API_KEY, BRAVE_SEARCH_API_KEYS, COMPETITOR_ACCOUNTS
from pipeline.analyzer import _call_compatible_json_completion
from pipeline.types import TopicPayload

SearchFn = Callable[[Any, list[str]], Awaitable[tuple[list[dict[str, str]], list[str]]]]
COMPETITOR_ANALYSIS_PROMPT_PATH = Path(__file__).resolve().parent.parent / "config" / "prompts" / "competitor_analysis.txt"


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (value or "").strip().lower())
    return cleaned.strip("_") or "account"


def _competitor_source(account: dict[str, Any]) -> str:
    return f"competitor_{_slugify(str(account.get('name') or 'account'))}"


def _build_competitor_query(account: dict[str, Any]) -> str:
    explicit = str(account.get("search_keyword") or "").strip()
    if explicit:
        return explicit
    name = str(account.get("name") or "").strip()
    platform = str(account.get("platform") or "").strip().lower()
    platform_hint = {
        "douyin": "site:douyin.com",
        "shipinhao": "site:channels.weixin.qq.com",
        "xiaohongshu": "site:xiaohongshu.com",
    }.get(platform, "")
    return " ".join(part for part in [name, platform_hint, "最新视频"] if part).strip()


def _decorate_items(items: list[dict[str, str]], account: dict[str, Any]) -> list[TopicPayload]:
    source = _competitor_source(account)
    name = str(account.get("name") or "").strip() or "对标账号"
    platform = str(account.get("platform") or "").strip() or ""
    decorated: list[TopicPayload] = []
    for item in items:
        snippet = str(item.get("raw_snippet") or "").strip()
        prefix = " | ".join(part for part in [name, platform] if part)
        decorated.append(
            {
                **item,
                "source": source,
                "source_type": "competitor",
                "raw_snippet": f"{prefix} | {snippet}".strip(" |"),
            }
        )
    return decorated


async def collect_competitor_topics(
    ext_client,
    int_client,
    *,
    brave_search: SearchFn,
    baidu_search: SearchFn,
) -> tuple[list[TopicPayload], list[str]]:
    items: list[TopicPayload] = []
    errors: list[str] = []

    for account in COMPETITOR_ACCOUNTS:
        query = _build_competitor_query(account)
        if not query:
            continue

        source = _competitor_source(account)
        if BRAVE_SEARCH_API_KEYS:
            brave_items, brave_errors = await brave_search(ext_client, [query])
            if brave_items:
                items.extend(_decorate_items(brave_items, account))
                continue
            if brave_errors:
                errors.extend([f"Competitor brave failed {source}: {err}" for err in brave_errors])

        if BAIDU_API_KEY:
            baidu_items, baidu_errors = await baidu_search(int_client, [query])
            if baidu_items:
                items.extend(_decorate_items(baidu_items, account))
            if baidu_errors:
                errors.extend([f"Competitor baidu failed {source}: {err}" for err in baidu_errors])
        elif not BRAVE_SEARCH_API_KEYS:
            errors.append(f"Competitor search skipped {source}: no Brave or Baidu credentials configured")

    return items, errors


def _prompt_text() -> str:
    return COMPETITOR_ANALYSIS_PROMPT_PATH.read_text(encoding="utf-8")


def _fallback_report(items: list[dict[str, Any]], *, days: int) -> dict[str, Any]:
    report_items = []
    for item in items:
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        report_items.append(
            {
                "source": source,
                "title": title,
                "summary": str(item.get("raw_snippet") or "").strip() or "对标账号近期持续在讲相近主题。",
                "borrowable_point": "对标标题通常先抛痛点，再给一个明确判断。",
                "differentiated_angle": "添爸更适合补上政策、支付和家庭决策层面的解释。",
                "url": item.get("url"),
            }
        )
    return {"days": days, "count": len(report_items), "items": report_items, "mode": "fallback"}


async def generate_competitor_report(
    int_client,
    topics: list[dict[str, Any]],
    *,
    days: int = 7,
) -> dict[str, Any]:
    if not topics:
        return {"days": days, "count": 0, "items": [], "mode": "empty"}

    prompt = _prompt_text()
    payload_items = [
        {
            "input_index": idx,
            "title": str(topic.get("title") or ""),
            "source": str(topic.get("source") or ""),
            "raw_snippet": str(topic.get("raw_snippet") or ""),
            "url": str(topic.get("url") or ""),
        }
        for idx, topic in enumerate(topics)
    ]
    try:
        parsed_items, _usage = await _call_compatible_json_completion(
            int_client,
            model=ANALYZE_MODEL,
            prompt=prompt,
            user_content="INPUT_COMPETITOR_TOPICS=\n" + json.dumps(payload_items, ensure_ascii=False),
        )
    except Exception:
        return _fallback_report(topics, days=days)

    by_index = {
        int(item.get("input_index")): item
        for item in parsed_items
        if str(item.get("input_index", "")).isdigit()
    }
    report_items = []
    for index, topic in enumerate(topics):
        parsed = by_index.get(index, {})
        report_items.append(
            {
                "source": str(topic.get("source") or ""),
                "title": str(topic.get("title") or ""),
                "summary": str(parsed.get("summary") or topic.get("raw_snippet") or "").strip(),
                "borrowable_point": str(parsed.get("borrowable_point") or "对标标题先抛问题再给判断。").strip(),
                "differentiated_angle": str(parsed.get("differentiated_angle") or "添爸补上政策和家庭决策视角。").strip(),
                "url": topic.get("url"),
            }
        )
    return {"days": days, "count": len(report_items), "items": report_items, "mode": "llm"}
