from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from pipeline import feedback_review


def test_build_review_dataset_maps_casey_labels(monkeypatch):
    monkeypatch.setattr(
        feedback_review,
        "load_casey_profile",
        lambda: {
            "content_mix": {
                "lines": [
                    {"key": "public_issue", "name": "医疗公共议题"},
                    {"key": "family_anxiety", "name": "家庭健康焦虑"},
                ],
                "roles": [
                    {"key": "spread", "name": "传播款"},
                    {"key": "save", "name": "收藏款"},
                ],
            }
        },
    )
    topics = [
        SimpleNamespace(
            topic_id="topic-1",
            title="医保新规影响哪些人",
            topic_line_primary="public_issue",
            content_role="save",
            perf_views=120000,
            perf_likes=3200,
            perf_comments=400,
            perf_shares=180,
            perf_collects=900,
            perf_watch_rate=55,
            publish_at="2026-03-23T12:30:00Z",
            publish_url="https://example.com/video/1",
        )
    ]

    dataset = feedback_review.build_review_dataset(topics)

    assert dataset["platform"] == "douyin"
    assert len(dataset["entries"]) == 1
    entry = dataset["entries"][0]
    assert entry["content_line"] == "医疗公共议题"
    assert entry["content_type"] == "收藏款"
    assert entry["completion_rate"] == 0.55
    assert entry["views"] == 120000
    assert entry["publish_time"] == "12:30"


def test_run_feedback_weekly_cycle_skips_when_not_enough_topics(monkeypatch):
    async def fake_collect(_client):
        return {"status": "ok", "matched_topics": 2}

    async def fake_load_topics():
        return [
            SimpleNamespace(topic_id="a", perf_views=1000, perf_watch_rate=0.45),
            SimpleNamespace(topic_id="b", perf_views=2000, perf_watch_rate=0.52),
        ]

    monkeypatch.setattr(feedback_review, "collect_douyin_feedback", fake_collect)
    monkeypatch.setattr(feedback_review, "load_feedback_review_topics", fake_load_topics)
    monkeypatch.setattr(feedback_review, "FEEDBACK_WEEKLY_MIN_TOPICS", 5)

    result = asyncio.run(feedback_review.run_feedback_weekly_cycle(client=object()))

    assert result["status"] == "skipped"
    assert result["eligible_topics"] == 2
    assert "未达到阈值 5" in result["message"]


def test_run_feedback_weekly_cycle_generates_patch_and_notifies(monkeypatch, tmp_path):
    notified = []

    async def fake_collect(_client):
        return {"status": "ok", "matched_topics": 5}

    async def fake_load_topics():
        now = datetime(2026, 3, 23, 12, 0, tzinfo=UTC)
        return [
            SimpleNamespace(
                topic_id=f"topic-{idx}",
                title=f"标题 {idx}",
                topic_line_primary="public_issue",
                content_role="spread",
                perf_views=10000 + idx,
                perf_likes=100 + idx,
                perf_comments=10 + idx,
                perf_shares=5 + idx,
                perf_collects=12 + idx,
                perf_watch_rate=0.48,
                publish_at=now.isoformat().replace("+00:00", "Z"),
                updated_at=now,
                publish_url=f"https://example.com/{idx}",
            )
            for idx in range(5)
        ]

    def fake_generate_bundle(dataset, *, output_dir=feedback_review.FEEDBACK_WEEKLY_DIR, min_samples=3):
        pending_path = Path(tmp_path) / "pending_latest.json"
        patch = {
            "sd_weight_patch": {
                "医疗公共议题": {"delta": 0.05, "reason": "连续3条播放量>10万"}
            },
            "style_patch": [
                {"rule": "标题带数字更好", "confidence": 0.72, "action": "标题尽量加入具体数字"}
            ],
        }
        pending_path.write_text("{}", encoding="utf-8")
        return {
            "dataset_path": str(Path(tmp_path) / "content_data.json"),
            "patch_path": str(Path(tmp_path) / "patches.json"),
            "pending_path": str(pending_path),
            "patch": patch,
        }

    async def fake_send_casey_message(_client, text):
        notified.append(text)
        return {"ok": True}

    monkeypatch.setattr(feedback_review, "collect_douyin_feedback", fake_collect)
    monkeypatch.setattr(feedback_review, "load_feedback_review_topics", fake_load_topics)
    monkeypatch.setattr(feedback_review, "generate_review_patch_bundle", fake_generate_bundle)
    monkeypatch.setattr(feedback_review, "send_casey_message", fake_send_casey_message)
    monkeypatch.setattr(feedback_review, "FEEDBACK_WEEKLY_MIN_TOPICS", 5)

    result = asyncio.run(feedback_review.run_feedback_weekly_cycle(client=object()))

    assert result["status"] == "ok"
    assert result["eligible_topics"] == 5
    assert result["weight_patch_count"] == 1
    assert result["style_patch_count"] == 1
    assert result["notified"] is True
    assert "patch 已生成，暂未自动应用" in notified[0]
    assert "医疗公共议题: +0.05 连续3条播放量>10万" in notified[0]

