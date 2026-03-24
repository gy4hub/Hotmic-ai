from __future__ import annotations

import asyncio

from pipeline import feedback_review


def test_run_feedback_weekly_cycle_end_to_end(monkeypatch):
    async def fake_collect(_client):
        return {"status": "ok", "collected": 3}

    async def fake_topics(*, platform="douyin", since_days=30, limit=100):
        return [
            {
                "topic_id": "topic-1",
                "title": "A",
                "topic_line_primary": "public_issue",
                "content_role": "spread",
                "perf_views": 10000,
                "perf_watch_rate": 0.45,
                "publish_at": "2026-03-23T10:00:00+00:00",
                "publish_url": "https://example.com/1",
            }
        ] * 5

    def fake_bundle(dataset: dict, *, output_dir=None, min_samples=3):
        assert len(dataset["entries"]) == 5
        return {
            "dataset_path": "/tmp/content_data.json",
            "patch_path": "/tmp/patches.json",
            "pending_path": "/tmp/pending_latest.json",
            "patch": {
                "sd_weight_patch": {
                    "医疗公共议题": {"delta": 0.05, "reason": "连续表现优秀"}
                },
                "style_patch": [
                    {"action": "开头先给结论", "confidence": 0.82}
                ],
            },
        }

    sent_messages: list[str] = []

    async def fake_send(_client, message: str):
        sent_messages.append(message)
        return {"ok": True}

    monkeypatch.setattr(feedback_review, "collect_douyin_feedback", fake_collect)
    monkeypatch.setattr(feedback_review, "load_feedback_review_topics", fake_topics)
    monkeypatch.setattr(feedback_review, "generate_review_patch_bundle", fake_bundle)
    monkeypatch.setattr(feedback_review, "send_casey_message", fake_send)

    result = asyncio.run(feedback_review.run_feedback_weekly_cycle(client=object()))

    assert result["status"] == "ok"
    assert result["eligible_topics"] == 5
    assert result["weight_patch_count"] == 1
    assert result["style_patch_count"] == 1
    assert result["notified"] is True
    assert "patch 已生成" in sent_messages[0]
    assert "医疗公共议题" in sent_messages[0]
