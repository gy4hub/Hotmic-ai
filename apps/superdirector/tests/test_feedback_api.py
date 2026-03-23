from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tools import api_routes


class DummyRequest:
    def __init__(self):
        self.app = SimpleNamespace(state=SimpleNamespace(int_client=object()))


def test_feedback_collect_all_returns_multi_platform_payload(monkeypatch):
    async def fake_collect_douyin(_client):
        return {"status": "ok", "platform": "douyin"}

    async def fake_collect_xhs(_client):
        return {"status": "ok", "platform": "xiaohongshu"}

    monkeypatch.setattr(api_routes, "collect_douyin_feedback", fake_collect_douyin)
    monkeypatch.setattr(api_routes, "collect_xhs_feedback", fake_collect_xhs)

    result = asyncio.run(api_routes.feedback_collect(DummyRequest(), platform="all"))

    assert result["douyin"]["platform"] == "douyin"
    assert result["xiaohongshu"]["platform"] == "xiaohongshu"
    assert result["shipinhao"]["status"] == "skipped"
