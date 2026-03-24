from __future__ import annotations

import asyncio
from types import SimpleNamespace

import api.routes as api_routes


class DummyRequest:
    def __init__(self):
        self.app = SimpleNamespace(state=SimpleNamespace(int_client=object()))


class DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        class DummyResult:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return self

            def all(self):
                return self._rows

        return DummyResult(
            [
                SimpleNamespace(
                    title="老蒋巨靠谱：医保药为什么进了还难开",
                    source="competitor_老蒋巨靠谱",
                    raw_snippet="老蒋巨靠谱 | douyin | 搜索摘要",
                    url="https://douyin.com/1",
                    created_at=None,
                ),
                SimpleNamespace(
                    title="三甲传真：创新药进院卡在哪",
                    source="competitor_三甲传真",
                    raw_snippet="三甲传真 | shipinhao | 搜索摘要",
                    url="https://channels.weixin.qq.com/1",
                    created_at=None,
                ),
            ]
        )


def test_competitor_report_returns_recent_topics(monkeypatch):
    async def fake_generate_competitor_report(_int_client, topics, *, days):
        assert days == 7
        assert len(topics) == 2
        return {
            "days": days,
            "count": 2,
            "mode": "fallback",
            "items": [
                {
                    "source": topics[0]["source"],
                    "title": topics[0]["title"],
                    "summary": "对标账号近期在讲医保进院难",
                    "borrowable_point": "先抛问题再给判断",
                    "differentiated_angle": "添爸补支付体系视角",
                    "url": topics[0]["url"],
                }
            ],
        }

    monkeypatch.setattr(api_routes, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(api_routes, "generate_competitor_report", fake_generate_competitor_report)

    result = asyncio.run(api_routes.competitor_report(DummyRequest(), days=7))

    assert result["count"] == 2
    assert result["items"][0]["borrowable_point"] == "先抛问题再给判断"
    assert result["topics"][1]["source"] == "competitor_三甲传真"
