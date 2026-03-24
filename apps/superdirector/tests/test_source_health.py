from __future__ import annotations

import asyncio
from types import SimpleNamespace

from compat import UTC
from tools import api_routes


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


class DummyClient:
    def __init__(self, handler):
        self._handler = handler

    async def request(self, method, url, **kwargs):
        return await self._handler(method, url, **kwargs)


def test_build_source_health_includes_all_sources(monkeypatch, tmp_path):
    rss_xml = """
    <rss><channel>
      <item><title>微信文章A</title><link>https://wx/1</link><description>摘要A</description></item>
    </channel></rss>
    """
    official_html = """
    <html><body>
      <a href="/n1">国家药监局发布药品召回公告</a>
    </body></html>
    """
    official_api = {
        "results": [
            {
                "classification": "Class II",
                "product_description": "Infusion Pump",
                "reason_for_recall": "Software issue may delay treatment",
                "report_date": "20260301",
                "recall_number": "D-0001-2026",
            }
        ]
    }

    async def fake_request(method, url, **kwargs):
        if "rss" in url:
            return DummyResponse(text=rss_xml)
        if "api.search.brave.com" in url:
            return DummyResponse(json_data={"web": {"results": [{"title": "结果", "url": "https://a", "description": "d"}]}})
        if "api.tavily.com" in url:
            return DummyResponse(json_data={"results": [{"title": "Tavily结果", "url": "https://t.local/1", "content": "c"}]})
        if "qianfan.baidubce.com" in url:
            return DummyResponse(json_data={"references": [{"title": "百度结果", "url": "https://baidu.local/1"}]})
        if "api.fda.gov" in url:
            return DummyResponse(json_data=official_api)
        return DummyResponse(text=official_html)

    async def fake_wewe_health(_client):
        return {"status": "ok", "message": "WeWe 正常", "needs_relogin": False}

    cache_file = tmp_path / "search_contents_2026-03-17.json"
    cache_file.write_text("[]", encoding="utf-8")
    cache_file.touch()
    monkeypatch.setattr(api_routes, "get_wewe_health", fake_wewe_health)
    monkeypatch.setattr(api_routes, "_latest_mediacrawler_file", lambda _dirs: cache_file)
    monkeypatch.setattr(api_routes, "RSS_SOURCES", [{"url": "http://rss.local/feed.rss", "source": "wechat_rss"}])
    monkeypatch.setattr(
        api_routes,
        "RSS_DISCOVERY_BASKET_SOURCES",
        [{"url": "http://rss.local/discovery.rss", "source": "rss_stats_release"}],
    )
    monkeypatch.setattr(api_routes, "OFFICIAL_HTML_SOURCES", [{"url": "https://official.local/news", "source": "nmpa_news", "keywords": ["药"]}])
    monkeypatch.setattr(api_routes, "OFFICIAL_API_SOURCES", [{"url": "https://api.fda.gov/drug/enforcement.json", "source": "fda_safety", "params": {"limit": 1}}])
    monkeypatch.setattr(api_routes, "MEDIA_CRAWLER_SOURCE_SPECS", [{"source": "mediacrawler_xhs", "directories": ["xhs"]}])
    monkeypatch.setattr(api_routes, "BRAVE_QUERY_SPECS", [{"source": "brave_policy", "query": "医保政策", "freshness": "pw"}])
    monkeypatch.setattr(api_routes, "BRAVE_SEARCH_API_KEYS", ("test-key",))
    monkeypatch.setattr(api_routes, "TAVILY_ENABLED", True)
    monkeypatch.setattr(api_routes, "TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr(api_routes, "TAVILY_RESULT_COUNT", 5)
    monkeypatch.setattr(api_routes, "BAIDU_API_KEY", "baidu-key")
    monkeypatch.setattr(api_routes, "MEDIA_CRAWLER_MAX_AGE_HOURS", 6)
    state = SimpleNamespace(ext_client=DummyClient(fake_request), int_client=DummyClient(fake_request))

    result = asyncio.run(api_routes._build_source_health(state))

    assert result["wewe_rss"]["status"] == "ok"
    assert result["wechat_rss"]["status"] == "ok"
    assert result["brave_search"]["status"] == "ok"
    assert result["tavily_search"]["status"] == "ok"
    assert result["baidu_search"]["status"] == "ok"
    assert result["nmpa_news"]["status"] == "ok"
    assert result["fda_safety"]["status"] == "ok"
    assert result["mediacrawler_xhs"]["status"] == "ok"
    assert "latest_file" in result["mediacrawler_xhs"]


def test_check_brave_source_402_becomes_warning(monkeypatch):
    async def fake_request(_method, _url, **_kwargs):
        return DummyResponse(text="payment required", status_code=402)

    monkeypatch.setattr(api_routes, "BRAVE_SEARCH_API_KEYS", ("test-key",))
    monkeypatch.setattr(api_routes, "BRAVE_QUERY_SPECS", [{"source": "brave_policy", "query": "医保政策", "freshness": "pw"}])

    result = asyncio.run(api_routes._check_brave_source(DummyClient(fake_request)))

    assert result["status"] == "warning"
    assert "额度" in result["message"]


def test_check_brave_source_switches_to_second_key(monkeypatch):
    calls: list[str] = []

    async def fake_request(_method, _url, **kwargs):
        token = kwargs["headers"]["X-Subscription-Token"]
        calls.append(token)
        if token == "key-1":
            return DummyResponse(text="payment required", status_code=402)
        return DummyResponse(json_data={"web": {"results": [{"title": "结果", "url": "https://a", "description": "d"}]}})

    monkeypatch.setattr(api_routes, "BRAVE_SEARCH_API_KEYS", ("key-1", "key-2"))
    monkeypatch.setattr(api_routes, "BRAVE_QUERY_SPECS", [{"source": "brave_policy", "query": "医保政策", "freshness": "pw"}])

    result = asyncio.run(api_routes._check_brave_source(DummyClient(fake_request)))

    assert result["status"] == "ok"
    assert "切换到第 2 个 key" in result["message"]
    assert calls == ["key-1", "key-2"]


def test_check_tavily_source_disabled(monkeypatch):
    monkeypatch.setattr(api_routes, "TAVILY_ENABLED", False)

    result = asyncio.run(api_routes._check_tavily_source(DummyClient(lambda *_args, **_kwargs: None)))

    assert result["status"] == "disabled"


def test_check_rss_source_503_is_error_for_disabled_weibo_path(monkeypatch):
    async def fake_request(_method, _url, **_kwargs):
        return DummyResponse(text="Service unavailable", status_code=503)

    result = asyncio.run(
        api_routes._check_rss_source(
            DummyClient(fake_request),
            {"url": "http://rss.local/discovery.rss", "source": "rss_stats_release"},
        )
    )

    assert result["status"] == "error"
