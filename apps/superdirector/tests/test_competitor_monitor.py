from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pipeline import competitor_monitor


def test_build_competitor_query_prefers_explicit_search_keyword():
    query = competitor_monitor._build_competitor_query(
        {"name": "老蒋巨靠谱", "platform": "douyin", "search_keyword": "老蒋巨靠谱 医保"}
    )

    assert query == "老蒋巨靠谱 医保"


def test_build_competitor_query_falls_back_to_platform_hint():
    query = competitor_monitor._build_competitor_query(
        {"name": "三甲传真", "platform": "shipinhao"}
    )

    assert query == "三甲传真 site:channels.weixin.qq.com 最新视频"


def test_collect_competitor_topics_uses_brave_and_decorates_source(monkeypatch):
    monkeypatch.setattr(
        competitor_monitor,
        "COMPETITOR_ACCOUNTS",
        [{"name": "老蒋巨靠谱", "platform": "douyin", "search_keyword": "老蒋巨靠谱 医保"}],
    )
    monkeypatch.setattr(competitor_monitor, "BRAVE_SEARCH_API_KEYS", ("test-key",))
    monkeypatch.setattr(competitor_monitor, "BAIDU_API_KEY", "")

    async def fake_brave_search(_client, queries):
        assert queries == ["老蒋巨靠谱 医保"]
        return (
            [
                {
                    "title": "医保进院难最新解读",
                    "url": "https://douyin.com/video/1",
                    "source": "brave_search",
                    "timestamp": "",
                    "raw_snippet": "搜索摘要",
                }
            ],
            [],
        )

    async def fake_baidu_search(_client, queries):
        raise AssertionError("baidu should not be called when brave succeeds")

    items, errors = asyncio.run(
        competitor_monitor.collect_competitor_topics(
            SimpleNamespace(),
            SimpleNamespace(),
            brave_search=fake_brave_search,
            baidu_search=fake_baidu_search,
        )
    )

    assert errors == []
    assert items[0]["source"] == "competitor_老蒋巨靠谱"
    assert items[0]["source_type"] == "competitor"
    assert "老蒋巨靠谱" in items[0]["raw_snippet"]


def test_collect_competitor_topics_falls_back_to_baidu(monkeypatch):
    monkeypatch.setattr(
        competitor_monitor,
        "COMPETITOR_ACCOUNTS",
        [{"name": "三甲传真", "platform": "shipinhao", "search_keyword": "三甲传真 医疗"}],
    )
    monkeypatch.setattr(competitor_monitor, "BRAVE_SEARCH_API_KEYS", ("test-key",))
    monkeypatch.setattr(competitor_monitor, "BAIDU_API_KEY", "baidu-key")

    async def fake_brave_search(_client, queries):
        return [], ["Brave fetch failed"]

    async def fake_baidu_search(_client, queries):
        assert queries == ["三甲传真 医疗"]
        return (
            [
                {
                    "title": "三甲传真最新视频",
                    "url": "https://channels.weixin.qq.com/1",
                    "source": "baidu_search",
                    "timestamp": "",
                    "raw_snippet": "百度摘要",
                }
            ],
            [],
        )

    items, errors = asyncio.run(
        competitor_monitor.collect_competitor_topics(
            SimpleNamespace(),
            SimpleNamespace(),
            brave_search=fake_brave_search,
            baidu_search=fake_baidu_search,
        )
    )

    assert any("competitor_三甲传真" in error for error in errors)
    assert items[0]["source"] == "competitor_三甲传真"
