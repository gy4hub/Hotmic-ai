import asyncio
import json
from types import SimpleNamespace

import pytest

from pipeline import collector


class DummyResponse:
    def __init__(self, *, text="", json_data=None, status_code=200):
        self.text = text
        self._json_data = json_data or {}
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


@pytest.mark.parametrize(
    ("html", "keywords", "expected_titles"),
    [
        (
            """
            <html><body>
              <a href="/news/1.html">国家药监局发布药品召回公告</a>
              <a href="/about.html">关于我们</a>
              <a href="https://example.com/2">医保目录调整新进展</a>
            </body></html>
            """,
            ["药", "医保"],
            ["国家药监局发布药品召回公告", "医保目录调整新进展"],
        ),
    ],
)
def test_parse_html_listing_filters_keywords(html, keywords, expected_titles):
    items = collector._parse_html_listing(
        html,
        base_url="https://example.com/list/",
        source="official",
        keywords=keywords,
        limit=5,
    )

    assert [item["title"] for item in items] == expected_titles
    assert items[0]["url"] == "https://example.com/news/1.html"


def test_parse_html_listing_respects_url_patterns():
    html = """
    <html><body>
      <a href="/2026-03/17/c_123.htm">Policy measures to advance drug regulation reform</a>
      <a href="/medicaldevices.html">Medical Devices +</a>
    </body></html>
    """
    items = collector._parse_html_listing(
        html,
        base_url="https://english.nmpa.gov.cn/news.html",
        source="nmpa_news",
        keywords=["drug", "medical"],
        url_patterns=[r"/20\d{2}-\d{2}/\d{2}/c_\d+\.htm$"],
        limit=5,
    )

    assert [item["title"] for item in items] == ["Policy measures to advance drug regulation reform"]


def test_parse_fda_enforcement():
    payload = {
        "results": [
            {
                "classification": "Class II",
                "product_description": "Infusion Pump",
                "reason_for_recall": "Software issue may delay treatment",
                "distribution_pattern": "US nationwide",
                "status": "Ongoing",
                "report_date": "20260301",
                "recall_number": "D-0001-2026",
            }
        ]
    }

    items = collector._parse_fda_enforcement(payload, source="fda_safety", limit=5)

    assert len(items) == 1
    assert items[0]["title"] == "Class II | Infusion Pump"
    assert "delay treatment" in items[0]["raw_snippet"]
    assert "D-0001-2026" in items[0]["url"]


@pytest.mark.parametrize(
    ("source", "url"),
    [
        ("rss_36kr", "https://36kr.com/p/1"),
        ("rss_huxiu", "https://www.huxiu.com/article/1.html"),
        ("rss_ifanr", "https://www.ifanr.com/1"),
        ("rss_geekpark", "https://www.geekpark.net/news/1"),
        ("rss_dxy", "https://www.dxy.cn/bbs/newweb/pc/post/1"),
    ],
)
def test_parse_rss_supports_new_discovery_sources(source, url):
    rss_xml = f"""
    <rss><channel>
      <item>
        <title>{source} 标题</title>
        <link>{url}</link>
        <description>{source} 摘要</description>
        <pubDate>Tue, 24 Mar 2026 08:00:00 GMT</pubDate>
      </item>
    </channel></rss>
    """

    items = collector._parse_rss(rss_xml, source, limit=5)

    assert len(items) == 1
    assert items[0]["source"] == source
    assert items[0]["title"] == f"{source} 标题"
    assert items[0]["url"] == url


def test_collect_topics_combines_rss_official_and_brave(monkeypatch):
    rss_xml = """
    <rss><channel>
      <item><title>微信文章A</title><link>https://wx/1</link><description>摘要A</description></item>
      <item><title>微信文章B</title><link>https://wx/2</link><description>摘要B</description></item>
    </channel></rss>
    """
    official_html = """
    <html><body>
      <a href="/n1">国家药监局发布新规</a>
      <a href="/n2">医保目录谈判新动向</a>
    </body></html>
    """

    async def fake_request_with_retry(_client, _method, url, **kwargs):
        if "feeds/all.rss" in url:
            return DummyResponse(text=rss_xml)
        if "weibo/search" in url:
            return DummyResponse(text="<rss><channel></channel></rss>")
        if "api.search.brave.com" in url:
            source = kwargs["params"]["q"]
            return DummyResponse(
                json_data={
                    "web": {
                        "results": [
                            {
                                "title": f"{source} 结果1",
                                "url": f"https://search.local/{hash(source) % 1000}/1",
                                "description": "搜索结果摘要",
                            }
                        ]
                    }
                }
            )
        if "qianfan.baidubce.com" in url:
            return DummyResponse(
                json_data={
                    "references": [
                        {
                            "title": "百度结果1",
                            "url": "https://baidu.local/1",
                            "page_content": "百度摘要",
                        }
                    ]
                }
            )
        return DummyResponse(text=official_html)

    monkeypatch.setattr(collector, "request_with_retry", fake_request_with_retry)
    monkeypatch.setattr(
        collector,
        "RSS_SOURCES",
        [
            {"url": "http://rss/feeds/all.rss", "source": "wechat_rss"},
            {"url": "http://rss/stats.rss", "source": "rss_stats_release"},
        ],
    )
    monkeypatch.setattr(collector, "RSS_DISCOVERY_BASKET_SOURCES", [])
    monkeypatch.setattr(
        collector,
        "OFFICIAL_HTML_SOURCES",
        [{"url": "https://official.local/news", "source": "official", "keywords": ["药", "医保"]}],
    )
    monkeypatch.setattr(collector, "OFFICIAL_API_SOURCES", [])
    monkeypatch.setattr(collector, "SEARCH_KEYWORDS", {"hook": ["医保政策", "药品安全"], "insight": ["drug safety"], "industry": ["IVD 集采"]})
    monkeypatch.setattr(collector, "SEARCH_PICKS_PER_LAYER", 1)
    monkeypatch.setattr(collector, "BRAVE_SEARCH_API_KEYS", ("test-key",))
    monkeypatch.setattr(collector, "BAIDU_API_KEY", "baidu-key")
    monkeypatch.setattr(collector, "RAW_POOL_LIMIT", 10)
    monkeypatch.setattr(collector, "BRAVE_QUERY_LIMIT", 5)
    monkeypatch.setattr(collector, "BRAVE_RESULT_COUNT", 1)
    monkeypatch.setattr(collector, "BAIDU_RESULT_COUNT", 1)
    monkeypatch.setattr(collector, "SITE_SEARCH_TARGETS", [])
    monkeypatch.setattr(collector, "EVERGREEN_DAILY_COUNT", 0)
    monkeypatch.setattr(collector, "_collect_mediacrawler", lambda: asyncio.sleep(0, result=([], [])))
    monkeypatch.setattr(collector, "collect_competitor_topics", lambda *_args, **_kwargs: asyncio.sleep(0, result=([], [])))

    items, errors = asyncio.run(collector.collect_topics(SimpleNamespace(), SimpleNamespace()))

    assert errors == []
    assert len(items) == 6
    assert {item["source"] for item in items} == {
        "wechat_rss",
        "official",
        "brave_search",
        "baidu_search",
    }
    assert any(item["source"] == "official" for item in items)
    assert any(item["source"] == "brave_search" for item in items)
    assert any(item["source"] == "baidu_search" for item in items)


def test_collect_evergreen_respects_cooldown_and_limit(monkeypatch, tmp_path):
    pool_path = tmp_path / "evergreen.json"
    pool_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "topics": [
                    {
                        "id": "eg_1",
                        "title": "医保报销怎么看",
                        "persona_fit": "政策解读",
                        "last_published": None,
                        "cooldown_days": 90,
                        "keywords": ["医保"],
                        "angle_suggestions": ["先讲真实案例"],
                    },
                    {
                        "id": "eg_2",
                        "title": "老人药箱怎么整理",
                        "persona_fit": "家庭管理",
                        "last_published": "2026-03-10",
                        "cooldown_days": 30,
                        "keywords": ["药箱"],
                        "angle_suggestions": ["讲常见误区"],
                    },
                    {
                        "id": "eg_3",
                        "title": "体检单怎么看",
                        "persona_fit": "消费避坑",
                        "last_published": "2025-10-01",
                        "cooldown_days": 30,
                        "keywords": ["体检"],
                        "angle_suggestions": ["给出判断顺序"],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(collector, "EVERGREEN_POOL_PATH", str(pool_path))
    monkeypatch.setattr(collector, "EVERGREEN_DAILY_COUNT", 2)
    monkeypatch.setattr(collector, "sample", lambda items, count: items[:count])

    items, errors = asyncio.run(collector._collect_evergreen())

    assert errors == []
    assert [item["evergreen_id"] for item in items] == ["eg_1", "eg_3"]
    assert all(item["source"] == "evergreen" for item in items)
    assert all(item["source_type"] == "evergreen" for item in items)


def test_mark_evergreen_published_updates_pool(tmp_path):
    pool_path = tmp_path / "evergreen.json"
    pool_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "topics": [{"id": "eg_1", "title": "医保报销怎么看", "last_published": None, "cooldown_days": 90}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    updated = collector.mark_evergreen_published("eg_1", published_at="2026-03-24T08:00:00Z", path=str(pool_path))
    payload = json.loads(pool_path.read_text(encoding="utf-8"))

    assert updated is True
    assert payload["topics"][0]["last_published"] == "2026-03-24"


def test_collect_brave_switches_to_second_key_on_402(monkeypatch):
    calls: list[str] = []

    class DummyResponse:
        def __init__(self, *, status_code=200, json_data=None):
            self.status_code = status_code
            self._json = json_data or {}

        def json(self):
            return self._json

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"status={self.status_code}")

    async def fake_request_with_retry(_client, _method, _url, **kwargs):
        token = kwargs["headers"]["X-Subscription-Token"]
        calls.append(token)
        if token == "key-1":
            return DummyResponse(status_code=402)
        return DummyResponse(json_data={"web": {"results": [{"title": "结果", "url": "https://ok", "description": "d"}]}})

    monkeypatch.setattr(collector, "request_with_retry", fake_request_with_retry)
    monkeypatch.setattr(collector, "BRAVE_SEARCH_API_KEYS", ("key-1", "key-2"))
    monkeypatch.setattr(collector, "BRAVE_RESULT_COUNT", 1)
    monkeypatch.setattr(collector, "BRAVE_QUERY_LIMIT", 1)

    items, errors = asyncio.run(collector._collect_brave(SimpleNamespace(), ["医保政策"]))

    assert errors == []
    assert len(items) == 1
    assert calls == ["key-1", "key-2"]


def test_build_site_search_query():
    query = collector._build_site_search_query(
        {"site": "mp.weixin.qq.com", "keyword": "赛柏蓝", "source": "wx_saibolan"}
    )

    assert query == "site:mp.weixin.qq.com 赛柏蓝"


def test_collect_site_searches_builds_queries_and_overrides_sources(monkeypatch):
    observed_queries: list[str] = []

    async def fake_collect_brave(_client, keywords):
        observed_queries.extend(keywords)
        return (
            [
                {
                    "title": f"{keywords[0]} 命中",
                    "url": f"https://result.local/{len(observed_queries)}",
                    "source": "brave_search",
                    "timestamp": "",
                    "raw_snippet": "snippet",
                }
            ],
            [],
        )

    monkeypatch.setattr(collector, "_collect_brave", fake_collect_brave)
    monkeypatch.setattr(collector, "BRAVE_SEARCH_API_KEYS", ("test-key",))
    monkeypatch.setattr(
        collector,
        "SITE_SEARCH_TARGETS",
        [
            {"site": "mp.weixin.qq.com", "keyword": "赛柏蓝", "source": "wx_saibolan"},
            {"site": "pedaily.cn", "keyword": "医疗 OR 医药 OR 器械", "source": "pedaily_med"},
        ],
    )

    items, errors = asyncio.run(collector._collect_site_searches(SimpleNamespace(), SimpleNamespace()))

    assert errors == []
    assert observed_queries == [
        "site:mp.weixin.qq.com 赛柏蓝",
        "site:pedaily.cn 医疗 OR 医药 OR 器械",
    ]
    assert {item["source"] for item in items} == {"wx_saibolan", "pedaily_med"}


def test_candidate_limit_prefers_raw_pool_limit(monkeypatch):
    monkeypatch.setattr(collector, "RAW_POOL_LIMIT", 80)
    monkeypatch.setattr(collector, "TOPICS_PER_RUN", 5)
    assert collector._candidate_limit() == 80


def test_build_keyword_batches_uses_expected_layers(monkeypatch):
    monkeypatch.setattr(
        collector,
        "SEARCH_KEYWORDS",
        {
            "hook": ["hook1", "hook2", "hook3"],
            "insight": ["insight1", "insight2", "insight3"],
            "industry": ["industry1", "industry2", "industry3"],
        },
    )
    monkeypatch.setattr(collector, "SEARCH_PICKS_PER_LAYER", 2)
    monkeypatch.setattr(collector, "TAVILY_QUERY_LIMIT", 3)

    brave_keywords, baidu_keywords, tavily_keywords = collector.build_keyword_batches()

    assert len(brave_keywords) == 4
    assert len(baidu_keywords) == 4
    assert len(tavily_keywords) == 3
    assert all(keyword.startswith(("hook", "insight")) for keyword in brave_keywords)
    assert all(keyword.startswith(("hook", "industry")) for keyword in baidu_keywords)
    assert all(keyword.startswith(("hook", "insight", "industry")) for keyword in tavily_keywords)


def test_deduplicate_items_uses_title_similarity():
    items = [
        {"title": "保健品老人被骗最新", "url": "https://a/1", "source": "baidu_search"},
        {"title": "保健品 老人被骗 最新", "url": "https://a/2", "source": "brave_search"},
        {"title": "体检报告看不懂白花钱", "url": "https://a/3", "source": "wechat_rss"},
    ]

    unique = collector._deduplicate_items(items)

    assert len(unique) == 2
    assert unique[0]["title"] == "保健品老人被骗最新"


def test_parse_mediacrawler_items(tmp_path):
    payload = [
        {
            "title": "千万别用医保卡给别人买药",
            "desc": "医保卡外借风险",
            "create_time": 1773700000,
            "aweme_url": "https://www.douyin.com/video/123",
            "liked_count": "100",
            "collected_count": "20",
            "comment_count": "5",
            "share_count": "3",
        }
    ]
    data_file = tmp_path / "search_contents_2026-03-17.json"
    data_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    items = collector._parse_mediacrawler_items(data_file, source="mediacrawler_douyin", limit=5)

    assert len(items) == 1
    assert items[0]["source"] == "mediacrawler_douyin"
    assert items[0]["title"] == "千万别用医保卡给别人买药"
    assert "点赞100" in items[0]["raw_snippet"]


def test_collect_mediacrawler_surfaces_refresh_error(monkeypatch):
    monkeypatch.setattr(
        collector,
        "MEDIA_CRAWLER_SOURCE_SPECS",
        [
            {
                "platform": "xiaohongshu",
                "platform_arg": "xhs",
                "keywords": "医保 创新药",
                "source": "mediacrawler_xhs",
                "directories": ["xhs"],
            }
        ],
    )
    monkeypatch.setattr(collector, "_latest_mediacrawler_file", lambda _dirs: None)

    async def fake_refresh(_platform_arg, _keywords):
        raise RuntimeError("cookie invalid")

    monkeypatch.setattr(collector, "_refresh_mediacrawler", fake_refresh)

    items, errors = asyncio.run(collector._collect_mediacrawler())

    assert items == []
    assert errors
    assert "cookie invalid" in errors[0]
