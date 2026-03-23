from __future__ import annotations

import asyncio
from types import SimpleNamespace

import scheduler


def test_morning_briefing_shows_frame_rejection_warning(monkeypatch):
    run = SimpleNamespace(id=11, raw_item_count=9)
    topics = [
        SimpleNamespace(
            title="第1条标题",
            topic_line_primary="public_issue",
            content_role="spread",
            platform_priority="douyin",
            creator_fit="strong",
            li_jie_value="click",
            zhang_auntie_value="forward",
            source="wechat_rss",
            timestamp="2026-03-23T08:00:00Z",
            date="2026-03-23",
            score_total=4.8,
            summary="摘要",
            raw_snippet="片段",
            frame_status="rejected",
            frame_rejection_reason="hook 过长：31 字，超过 25 字限制",
            url="https://example.com/1",
        )
    ]

    async def fake_get_latest_briefing_run(_session, *, date_str=None):
        return run

    async def fake_get_output_topics_for_run(_session, run_id, *, limit=None):
        assert run_id == 11
        return topics

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(scheduler.crud, "get_latest_briefing_run", fake_get_latest_briefing_run)
    monkeypatch.setattr(scheduler.crud, "get_output_topics_for_run", fake_get_output_topics_for_run)
    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(scheduler, "quality_gate", lambda _topics, _raw: (True, "通过"))

    text, skip_reason = asyncio.run(scheduler._format_morning_briefing())

    assert skip_reason is None
    assert "⚠️ 框架未通过质量检查" in text
    assert "hook 过长" in text
