from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from datetime import UTC, datetime, timedelta
from datetime import date
from html import unescape
from pathlib import Path
from random import sample
from typing import Any
from urllib.parse import urljoin

import feedparser

from config import (
    BAIDU_API_KEY,
    BAIDU_RESULT_COUNT,
    BRAVE_QUERY_LIMIT,
    BRAVE_RESULT_COUNT,
    BRAVE_SEARCH_API_KEYS,
    HTML_SOURCE_ITEM_LIMIT,
    MEDIA_CRAWLER_DIR,
    MEDIA_CRAWLER_DOUYIN_KEYWORDS,
    MEDIA_CRAWLER_ENABLED,
    MEDIA_CRAWLER_ITEM_LIMIT,
    MEDIA_CRAWLER_MAX_AGE_HOURS,
    MEDIA_CRAWLER_REFRESH_TIMEOUT,
    MEDIA_CRAWLER_XHS_KEYWORDS,
    PRIORITY_FALLBACK_KEYWORDS,
    RAW_POOL_LIMIT,
    RSS_DISCOVERY_BASKET_SOURCES,
    RSS_ITEM_LIMIT,
    SEARCH_KEYWORDS,
    SEARCH_PICKS_PER_LAYER,
    RSS_WECHAT,
    TAVILY_API_KEY,
    TAVILY_ENABLED,
    TAVILY_QUERY_LIMIT,
    TAVILY_RESULT_COUNT,
    TOPICS_PER_RUN,
)
from pipeline.types import TopicPayload
from pipeline.utils import request_with_retry

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
BAIDU_ENDPOINT = "https://qianfan.baidubce.com/v2/ai_search/web_search"
TAVILY_ENDPOINT = "https://api.tavily.com/search"
CURRENT_YEAR = date.today().year
OFFICIAL_FETCH_TIMEOUT = 12
SEARCH_DELAY_SECONDS = 3
TITLE_SIMILARITY_THRESHOLD = 0.8
OFFICIAL_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
MEDIA_CRAWLER_PATH = Path(MEDIA_CRAWLER_DIR)
MEDIA_CRAWLER_SOURCE_SPECS = [
    {
        "platform": "douyin",
        "platform_arg": "dy",
        "keywords": MEDIA_CRAWLER_DOUYIN_KEYWORDS,
        "source": "mediacrawler_douyin",
        "directories": ["douyin"],
    },
    {
        "platform": "xiaohongshu",
        "platform_arg": "xhs",
        "keywords": MEDIA_CRAWLER_XHS_KEYWORDS,
        "source": "mediacrawler_xhs",
        "directories": ["xhs", "xiaohongshu", "rednote"],
    },
]

RSS_SOURCES = [
    {"url": RSS_WECHAT, "source": "wechat_rss"},
] if RSS_WECHAT else []

BRAVE_QUERY_SPECS = [
    {"source": "brave_search", "query": "保健品 老人 被骗 最新", "freshness": "pw"},
    {"source": "brave_search", "query": "外泌体 美容 骗局 真相", "freshness": "pw"},
    {"source": "brave_search", "query": "CAR-T 治疗 费用 医保", "freshness": "pm"},
    {"source": "brave_search", "query": "脑机接口 瘫痪 康复 临床", "freshness": "pm"},
]

OFFICIAL_HTML_SOURCES = [
    {
        "url": "https://english.nmpa.gov.cn/news.html",
        "source": "nmpa_news",
        "url_patterns": [r"/20\d{2}-\d{2}/\d{2}/c_\d+\.htm$"],
        "keywords": [
            "drug",
            "medical",
            "device",
            "devices",
            "diagnostic",
            "ivd",
            "biotech",
            "innovation",
            "regulation",
            "recall",
            "warning",
            "approval",
            "policy",
        ],
    },
    {
        "url": "https://www.gov.cn/yaowen/liebiao/",
        "source": "govcn_policy",
        "keywords": [
            "医保",
            "药",
            "医药",
            "集采",
            "医疗器械",
            "体外诊断",
            "生物医药",
            "创新药",
            "健康",
            "卫生",
            "养老",
        ],
    },
    {
        "url": "https://www.who.int/teams/regulation-prequalification/incidents-and-SF/full-list-of-who-medical-product-alerts",
        "source": "who_alerts",
        "keywords": [
            "medical product",
            "alert",
            "substandard",
            "falsified",
            "safety",
            "diagnostic",
            "device",
            "IVD",
        ],
    },
    {
        "url": "https://www.statnews.com/category/pharma/",
        "source": "stat_pharma",
        "keywords": ["drug", "pharma", "biotech", "fda", "price", "shortage", "device", "diagnostic"],
    },
]

OFFICIAL_API_SOURCES = [
    {
        "url": "https://api.fda.gov/drug/enforcement.json",
        "source": "fda_safety",
        "params": {
            "search": "report_date:[20250101+TO+20301231]",
            "limit": 10,
        },
    },
]

ANCHOR_RE = re.compile(r"<a\b[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<text>.*?)</a>", re.I | re.S)
DATE_RE = re.compile(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})")
NMPA_ARTICLE_RE = re.compile(r"/20\d{2}-\d{2}/c_\d+\.htm$", re.I)


def _normalize_item(title: str, url: str, source: str, ts: str, snippet: str) -> dict[str, str]:
    normalized = {
        "title": title.strip() if title else "",
        "url": url,
        "source": source,
        "timestamp": ts,
        "raw_snippet": snippet.strip() if snippet else "",
    }
    normalized["fingerprint"] = _fingerprint_item(normalized)
    return normalized


def _normalize_title_for_match(title: str) -> str:
    return re.sub(r"\s+", "", (title or "").strip().lower())


def _fingerprint_item(item: dict[str, Any]) -> str:
    title = _normalize_title_for_match(str(item.get("title") or ""))
    url = str(item.get("url") or "").strip().lower()
    source = str(item.get("source") or "").strip().lower()
    raw = f"{source}|{title}|{url}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, _normalize_title_for_match(left), _normalize_title_for_match(right)).ratio()


def _clean_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_date(text: str) -> str:
    match = DATE_RE.search(text)
    if not match:
        return ""
    return match.group(1).replace("/", "-").replace(".", "-")


def _parse_rss(text: str, source: str, limit: int = RSS_ITEM_LIMIT) -> list[dict[str, str]]:
    feed = feedparser.parse(text)
    items: list[dict[str, str]] = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "")
        url = entry.get("link", "")
        ts = entry.get("published", "") or entry.get("updated", "") or ""
        snippet = entry.get("summary", "") or entry.get("description", "") or ""
        items.append(_normalize_item(title, url, source, ts, snippet))
    return items


def _keyword_match(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    text_lower = text.lower()
    return any(keyword.lower() in text_lower for keyword in keywords)


def _parse_html_listing(
    html: str,
    *,
    base_url: str,
    source: str,
    keywords: list[str],
    url_patterns: list[str] | None = None,
    limit: int = HTML_SOURCE_ITEM_LIMIT,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    compiled_patterns = [re.compile(pattern, re.I) for pattern in (url_patterns or [])]

    for match in ANCHOR_RE.finditer(html):
        href = match.group("href").strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue

        title = _clean_html_text(match.group("text"))
        if len(title) < 8:
            continue
        if not _keyword_match(title, keywords):
            continue

        url = urljoin(base_url, href)
        if compiled_patterns and not any(pattern.search(url) for pattern in compiled_patterns):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        ts = _extract_date(title)
        items.append(_normalize_item(title, url, source, ts, title))
        if len(items) >= limit:
            break

    return items


def _parse_fda_enforcement(data: dict[str, Any], *, source: str, limit: int = HTML_SOURCE_ITEM_LIMIT) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for entry in (data.get("results") or [])[:limit]:
        product = str(entry.get("product_description") or "").strip()
        reason = str(entry.get("reason_for_recall") or "").strip()
        classification = str(entry.get("classification") or "").strip()
        recall_number = str(entry.get("recall_number") or "").strip()
        report_date = str(entry.get("report_date") or "").strip()
        url = f"https://www.accessdata.fda.gov/scripts/ires/?Event={recall_number}" if recall_number else ""
        title_bits = [bit for bit in [classification, product] if bit]
        title = " | ".join(title_bits) or reason or "FDA recall notice"
        snippet = " | ".join(bit for bit in [reason, entry.get("distribution_pattern"), entry.get("status")] if bit)
        items.append(_normalize_item(title, url, source, report_date, snippet))
    return items


def _sample_layer_keywords(layer: str, count: int) -> list[str]:
    pool = list(SEARCH_KEYWORDS.get(layer) or [])
    if not pool:
        return []
    picks = min(max(count, 0), len(pool))
    return sample(pool, picks)


def _priority_keywords(layer: str, limit: int = 1) -> list[str]:
    pool = list(PRIORITY_FALLBACK_KEYWORDS.get(layer) or [])
    if not pool:
        return []
    return pool[: max(limit, 0)]


def build_keyword_batches() -> tuple[list[str], list[str], list[str]]:
    if any(layer in SEARCH_KEYWORDS for layer in ("hook", "insight", "industry")):
        hook_keywords = _sample_layer_keywords("hook", SEARCH_PICKS_PER_LAYER)
        insight_keywords = _sample_layer_keywords("insight", SEARCH_PICKS_PER_LAYER)
        industry_keywords = _sample_layer_keywords("industry", SEARCH_PICKS_PER_LAYER)
        brave_keywords = hook_keywords + insight_keywords
        baidu_keywords = hook_keywords + industry_keywords
        tavily_keywords = list(dict.fromkeys(hook_keywords + insight_keywords + industry_keywords))
        return brave_keywords[:4], baidu_keywords[:4], tavily_keywords[: min(max(TAVILY_QUERY_LIMIT, 1), 4)]

    public_keywords = _sample_layer_keywords("public_issue", 1)
    family_keywords = _sample_layer_keywords("family_anxiety", min(max(SEARCH_PICKS_PER_LAYER, 1), 2))
    consumer_keywords = _sample_layer_keywords("consumer_scam", min(max(SEARCH_PICKS_PER_LAYER, 1), 2))
    brave_keywords = list(dict.fromkeys(public_keywords + family_keywords + consumer_keywords))
    baidu_keywords = list(
        dict.fromkeys(
            _priority_keywords("family_anxiety", 1)
            + _priority_keywords("consumer_scam", 1)
            + _priority_keywords("public_issue", 1)
            + public_keywords
            + family_keywords
            + consumer_keywords
        )
    )
    tavily_keywords = list(dict.fromkeys(family_keywords + consumer_keywords + public_keywords))
    return brave_keywords[:5], baidu_keywords[:5], tavily_keywords[: min(max(TAVILY_QUERY_LIMIT, 1), 4)]


def _extract_baidu_references(payload: dict[str, Any]) -> list[dict[str, str]]:
    refs = payload.get("references") or []
    items: list[dict[str, str]] = []
    for ref in refs[:BAIDU_RESULT_COUNT]:
        title = str(ref.get("title") or ref.get("name") or "").strip()
        url = str(ref.get("url") or ref.get("page_url") or ref.get("web_url") or "").strip()
        snippet = str(
            ref.get("page_content")
            or ref.get("summary")
            or ref.get("snippet")
            or ref.get("content")
            or ""
        ).strip()
        if not title or not url:
            continue
        items.append(_normalize_item(title, url, "baidu_search", "", snippet))
    return items


async def collect_baidu(keywords: list[str], client) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not BAIDU_API_KEY or not keywords:
        return items

    for index, keyword in enumerate(keywords[:5]):
        payload = {
            "messages": [{"content": keyword, "role": "user"}],
            "edition": "standard",
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": BAIDU_RESULT_COUNT}],
            "search_filter": {},
            "search_recency_filter": "month",
            "safe_search": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        resp = await request_with_retry(
            client,
            "POST",
            BAIDU_ENDPOINT,
            headers={
                "Authorization": f"Bearer {BAIDU_API_KEY}",
                "Content-Type": "application/json; charset=utf-8",
                "X-Appbuilder-From": "superdirector",
            },
            content=body,
            timeout=OFFICIAL_FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code"):
            raise RuntimeError(str(data.get("message") or data.get("code")))
        items.extend(_extract_baidu_references(data))
        if index < min(len(keywords[:5]), 5) - 1:
            await asyncio.sleep(SEARCH_DELAY_SECONDS)
    return items


async def collect_tavily(keywords: list[str], client) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not TAVILY_ENABLED or not TAVILY_API_KEY or not keywords:
        return items

    capped_keywords = keywords[: min(max(TAVILY_QUERY_LIMIT, 1), 4)]
    for index, keyword in enumerate(capped_keywords):
        payload = {
            "api_key": TAVILY_API_KEY,
            "query": keyword,
            "search_depth": "basic",
            "topic": "general",
            "max_results": TAVILY_RESULT_COUNT,
            "include_answer": False,
            "include_raw_content": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        resp = await request_with_retry(
            client,
            "POST",
            TAVILY_ENDPOINT,
            headers={"Content-Type": "application/json; charset=utf-8"},
            content=body,
            timeout=OFFICIAL_FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        for result in (data.get("results") or [])[:TAVILY_RESULT_COUNT]:
            title = str(result.get("title") or "").strip()
            url = str(result.get("url") or "").strip()
            snippet = str(result.get("content") or result.get("snippet") or "").strip()
            if not title or not url:
                continue
            items.append(_normalize_item(title, url, "tavily_search", "", f"{keyword} | {snippet}"))
        if index < len(capped_keywords) - 1:
            await asyncio.sleep(SEARCH_DELAY_SECONDS)
    return items


async def _collect_rss(int_client) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    errors: list[str] = []
    for spec in RSS_SOURCES + list(RSS_DISCOVERY_BASKET_SOURCES):
        try:
            resp = await request_with_retry(
                int_client,
                "GET",
                spec["url"],
                timeout=OFFICIAL_FETCH_TIMEOUT,
                max_retries=1,
            )
            resp.raise_for_status()
            items.extend(_parse_rss(resp.text, spec["source"], limit=max(5, RSS_ITEM_LIMIT // 2)))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"RSS fetch failed {spec['url']}: {exc}")
    return items, errors


async def _collect_brave(ext_client, keywords: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    errors: list[str] = []

    if not BRAVE_SEARCH_API_KEYS or not keywords:
        return items, ["BRAVE_SEARCH_API_KEY missing"]

    effective_limit = min(max(BRAVE_QUERY_LIMIT, 1), 2 if TAVILY_API_KEY else 5)
    capped_keywords = keywords[:effective_limit]
    for index, keyword in enumerate(capped_keywords):
        ordered_keys = list(BRAVE_SEARCH_API_KEYS[index % len(BRAVE_SEARCH_API_KEYS) :]) + list(
            BRAVE_SEARCH_API_KEYS[: index % len(BRAVE_SEARCH_API_KEYS)]
        )
        last_error = ""
        exhausted_count = 0
        success = False
        for key in ordered_keys:
            try:
                resp = await request_with_retry(
                    ext_client,
                    "GET",
                    BRAVE_ENDPOINT,
                    params={
                        "q": keyword,
                        "count": BRAVE_RESULT_COUNT,
                        "search_lang": "zh-hans",
                        "country": "cn",
                        "freshness": "pw",
                    },
                    headers={"X-Subscription-Token": key},
                    timeout=OFFICIAL_FETCH_TIMEOUT,
                )
                if resp.status_code == 402:
                    exhausted_count += 1
                    last_error = "402 Payment Required"
                    continue
                resp.raise_for_status()
                data = resp.json()
                for result in data.get("web", {}).get("results", [])[:BRAVE_RESULT_COUNT]:
                    items.append(
                        _normalize_item(
                            result.get("title", ""),
                            result.get("url", ""),
                            "brave_search",
                            result.get("age", ""),
                            f"{keyword} | {result.get('description', '')}",
                        )
                    )
                success = True
                break
            except Exception as exc:  # noqa: BLE001
                text = str(exc)
                last_error = text
                if "402" in text:
                    exhausted_count += 1
                    continue
                break
        if not success:
            if exhausted_count == len(ordered_keys):
                errors.append(f"Brave fetch failed {keyword}: all configured keys exhausted (402)")
            else:
                errors.append(f"Brave fetch failed {keyword}: {last_error}")
        if index < len(capped_keywords) - 1:
            await asyncio.sleep(SEARCH_DELAY_SECONDS)

    return items, errors


async def _collect_baidu(int_client, keywords: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    if not BAIDU_API_KEY or not keywords:
        return [], ["BAIDU_API_KEY missing"]
    try:
        items = await collect_baidu(keywords[:5], int_client)
        return items, []
    except Exception as exc:  # noqa: BLE001
        return [], [f"Baidu fetch failed: {exc}"]


async def _collect_tavily(ext_client, keywords: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    if not TAVILY_ENABLED:
        return [], []
    if not TAVILY_API_KEY or not keywords:
        return [], []
    try:
        items = await collect_tavily(keywords, ext_client)
        return items, []
    except Exception as exc:  # noqa: BLE001
        return [], [f"Tavily fetch failed: {exc}"]


async def _collect_official_pages(ext_client) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    errors: list[str] = []

    for spec in OFFICIAL_HTML_SOURCES:
        try:
            resp = await request_with_retry(
                ext_client,
                "GET",
                spec["url"],
                headers={**OFFICIAL_PAGE_HEADERS, "Referer": spec["url"]},
                follow_redirects=True,
                timeout=OFFICIAL_FETCH_TIMEOUT,
            )
            resp.raise_for_status()
            parsed = _parse_html_listing(
                resp.text,
                base_url=spec["url"],
                source=spec["source"],
                keywords=spec["keywords"],
                url_patterns=spec.get("url_patterns"),
            )
            items.extend(parsed)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Official source fetch failed {spec['url']}: {exc}")

    return items, errors


async def _collect_official_apis(ext_client) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    errors: list[str] = []

    for spec in OFFICIAL_API_SOURCES:
        try:
            resp = await request_with_retry(
                ext_client,
                "GET",
                spec["url"],
                params=spec.get("params"),
                headers=OFFICIAL_PAGE_HEADERS,
                follow_redirects=True,
                timeout=OFFICIAL_FETCH_TIMEOUT,
            )
            resp.raise_for_status()
            if spec["source"] == "fda_safety":
                items.extend(_parse_fda_enforcement(resp.json(), source=spec["source"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Official source fetch failed {spec['url']}: {exc}")

    return items, errors


def _deduplicate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if url and url in seen_urls:
            continue
        if any(_title_similarity(title, existing.get("title", "")) >= TITLE_SIMILARITY_THRESHOLD for existing in unique):
            continue
        if url:
            seen_urls.add(url)
        if "fingerprint" not in item:
            item["fingerprint"] = _fingerprint_item(item)
        unique.append(item)
    return unique


def _candidate_limit() -> int:
    return max(RAW_POOL_LIMIT, max(TOPICS_PER_RUN, 1) * 2)


def _parse_mediacrawler_timestamp(value: Any) -> str:
    try:
        if value is None:
            return ""
        ts = int(value)
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:  # noqa: BLE001
        return ""


def _latest_mediacrawler_file(platform_dirs: list[str]) -> Path | None:
    candidates: list[Path] = []
    for platform_dir in platform_dirs:
        data_dir = MEDIA_CRAWLER_PATH / "data" / platform_dir / "json"
        if not data_dir.exists():
            continue
        candidates.extend(data_dir.glob("search_contents_*.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _parse_mediacrawler_items(path: Path, *, source: str, limit: int = MEDIA_CRAWLER_ITEM_LIMIT) -> list[dict[str, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []

    items: list[dict[str, str]] = []
    for entry in raw[:limit] if isinstance(raw, list) else []:
        title = str(entry.get("title") or entry.get("desc") or "").strip()
        url = str(entry.get("aweme_url") or entry.get("note_url") or entry.get("url") or "").strip()
        if not title or not url:
            continue
        metrics = [
            f"点赞{entry.get('liked_count')}" if entry.get("liked_count") else "",
            f"收藏{entry.get('collected_count')}" if entry.get("collected_count") else "",
            f"评论{entry.get('comment_count')}" if entry.get("comment_count") else "",
            f"转发{entry.get('share_count')}" if entry.get("share_count") else "",
        ]
        snippet = " | ".join(part for part in metrics if part)
        if entry.get("desc") and snippet:
            snippet = f"{entry.get('desc')} | {snippet}"
        elif entry.get("desc"):
            snippet = str(entry.get("desc"))
        items.append(
            _normalize_item(
                title,
                url,
                source,
                _parse_mediacrawler_timestamp(entry.get("create_time")),
                snippet,
            )
        )
    return items


async def _refresh_mediacrawler(platform_arg: str, keywords: str) -> None:
    if not MEDIA_CRAWLER_PATH.exists():
        raise FileNotFoundError(f"MediaCrawler directory missing: {MEDIA_CRAWLER_PATH}")
    python_bin = MEDIA_CRAWLER_PATH / "venv" / "bin" / "python3"
    if not python_bin.exists():
        raise FileNotFoundError(f"MediaCrawler venv missing: {python_bin}")

    cmd = [
        str(python_bin),
        str(MEDIA_CRAWLER_PATH / "main.py"),
        "--platform",
        platform_arg,
        "--lt",
        "cookie",
        "--type",
        "search",
        "--keywords",
        keywords,
        "--save_data_option",
        "json",
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(MEDIA_CRAWLER_PATH),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=MEDIA_CRAWLER_REFRESH_TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise TimeoutError(f"MediaCrawler {platform_arg} refresh timed out after {MEDIA_CRAWLER_REFRESH_TIMEOUT}s")
    if process.returncode:
        error_text = (stderr or b"").decode("utf-8", errors="ignore").strip()
        error_text = error_text.splitlines()[-1] if error_text else f"exit={process.returncode}"
        raise RuntimeError(f"MediaCrawler {platform_arg} refresh failed: {error_text}")


async def _collect_mediacrawler() -> tuple[list[dict[str, str]], list[str]]:
    if not MEDIA_CRAWLER_ENABLED and os.getenv("MEDIA_CRAWLER_ENABLED") is not None:
        return [], []

    items: list[dict[str, str]] = []
    errors: list[str] = []
    max_age = timedelta(hours=max(MEDIA_CRAWLER_MAX_AGE_HOURS, 1))

    for spec in MEDIA_CRAWLER_SOURCE_SPECS:
        latest = _latest_mediacrawler_file(spec["directories"])
        needs_refresh = True
        if latest and latest.exists():
            age = datetime.now(tz=UTC) - datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
            needs_refresh = age > max_age

        if needs_refresh:
            try:
                await _refresh_mediacrawler(spec["platform_arg"], spec["keywords"])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"MediaCrawler refresh failed {spec['platform']}: {exc}")

        latest = _latest_mediacrawler_file(spec["directories"])
        if not latest:
            continue

        parsed = _parse_mediacrawler_items(latest, source=spec["source"])
        if not parsed:
            errors.append(f"MediaCrawler parse returned no items: {latest}")
            continue
        items.extend(parsed)

    return items, errors


async def collect_fresh_topics(int_client, ext_client) -> tuple[list[TopicPayload], list[str]]:
    brave_keywords, baidu_keywords, tavily_keywords = build_keyword_batches()
    (
        (rss_items, rss_errors),
        (brave_items, brave_errors),
        (baidu_items, baidu_errors),
        (tavily_items, tavily_errors),
        (official_html_items, official_html_errors),
        (official_api_items, official_api_errors),
        (mediacrawler_items, mediacrawler_errors),
    ) = await asyncio.gather(
        _collect_rss(int_client),
        _collect_brave(ext_client, brave_keywords),
        _collect_baidu(int_client, baidu_keywords),
        _collect_tavily(ext_client, tavily_keywords),
        _collect_official_pages(ext_client),
        _collect_official_apis(ext_client),
        _collect_mediacrawler(),
    )

    official_items = official_html_items + official_api_items
    official_errors = official_html_errors + official_api_errors
    items = rss_items + official_items + mediacrawler_items + brave_items + baidu_items + tavily_items
    unique = _deduplicate_items(items)
    errors = rss_errors + official_errors + mediacrawler_errors + brave_errors + baidu_errors + tavily_errors
    return unique[: _candidate_limit()], errors


async def collect_topics(
    int_client,
    ext_client,
    *,
    pending_items: list[TopicPayload] | None = None,
) -> tuple[list[TopicPayload], list[str]]:
    fresh_items, errors = await collect_fresh_topics(int_client, ext_client)
    merged = list(pending_items or []) + fresh_items
    unique = _deduplicate_items(merged)
    return unique[: _candidate_limit()], errors
