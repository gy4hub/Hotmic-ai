from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from pipeline import feedback_collector


def test_save_douyin_cookie_sets_permissions(tmp_path, monkeypatch):
    cookie_path = tmp_path / ".douyin_cookie"
    monkeypatch.setattr(feedback_collector, "DOUYIN_COOKIE_PATH", cookie_path)

    saved = feedback_collector.save_douyin_cookie("sessionid=abc; ttwid=xyz")

    assert saved == cookie_path
    assert cookie_path.read_text(encoding="utf-8") == "sessionid=abc; ttwid=xyz"


def test_save_douyin_cookie_normalizes_cookie_json_path(tmp_path, monkeypatch):
    cookie_path = tmp_path / ".douyin_cookie"
    export_path = tmp_path / "cookies.json"
    export_path.write_text(
        json.dumps(
            [
                {"name": "sessionid", "value": "abc"},
                {"name": "ttwid", "value": "xyz"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(feedback_collector, "DOUYIN_COOKIE_PATH", cookie_path)

    feedback_collector.save_douyin_cookie(str(export_path))

    assert cookie_path.read_text(encoding="utf-8") == "sessionid=abc; ttwid=xyz"


def test_feedback_status_summary_counts_manual_fill(monkeypatch):
    rows_by_platform = {
        "douyin": [
            SimpleNamespace(
                topic_id="a",
                video_id="1",
                status="ok",
                play_count=100,
                digg_count=10,
                collect_count=5,
                comment_count=3,
                share_count=2,
                completion_rate=None,
                updated_at=datetime(2026, 3, 17, 7, 0, 0),
                error_message=None,
            ),
            SimpleNamespace(
                topic_id="b",
                video_id="2",
                status="error",
                play_count=None,
                digg_count=None,
                collect_count=None,
                comment_count=None,
                share_count=None,
                completion_rate=None,
                updated_at=datetime(2026, 3, 17, 7, 5, 0),
                error_message="403",
            ),
        ],
        "shipinhao": [],
        "xiaohongshu": [],
    }
    tracked_topics = {
        "douyin": [SimpleNamespace(publish_status="published", publish_url="https://douyin.com/1", publish_at=None)],
        "shipinhao": [SimpleNamespace(publish_status="published", publish_url="https://channels.weixin.qq.com/1", publish_at=None)],
        "xiaohongshu": [SimpleNamespace(publish_status="published", publish_url="https://www.xiaohongshu.com/explore/abc123", publish_at=None)],
    }

    async def fake_list_platform_feedback(_session, *, platform=None, limit=100):
        return rows_by_platform.get(platform, [])

    async def fake_get_topic_by_topic_id(_session, topic_id):
        return SimpleNamespace(perf_watch_rate=0.55 if topic_id == "b" else None)

    async def fake_list_topics_for_publish_matching(_session, *, platform, limit=200):
        return tracked_topics.get(platform, [])

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(feedback_collector.crud, "list_platform_feedback", fake_list_platform_feedback)
    monkeypatch.setattr(feedback_collector.crud, "get_topic_by_topic_id", fake_get_topic_by_topic_id)
    monkeypatch.setattr(feedback_collector.crud, "list_topics_for_publish_matching", fake_list_topics_for_publish_matching)
    monkeypatch.setattr(feedback_collector, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(feedback_collector, "douyin_cookie_exists", lambda: True)
    monkeypatch.setattr(feedback_collector, "feedback_manual_fill_link", lambda: "https://example.com/base")

    summary = asyncio.run(feedback_collector.feedback_status_summary())

    assert summary["auto_collected"] == 1
    assert summary["needs_manual_completion"] == 1
    assert summary["manual_fill_link"] == "https://example.com/base"
    assert "platforms" in summary
    assert summary["platforms"]["shipinhao"]["published_topics"] == 1
    assert summary["platforms"]["xiaohongshu"]["published_topics"] == 1
    assert any("视频号" in item for item in summary["recommendations"])
    assert any("小红书" in item for item in summary["recommendations"])


def test_collect_douyin_feedback_matches_work_list_item(monkeypatch):
    topic = SimpleNamespace(
        topic_id="topic-1",
        title="你的医保卡，现在能给外地父母用",
        publish_url=None,
        perf_watch_rate=None,
    )
    updates = []
    platform_feedback = []

    async def fake_fetch_work_list(_client, _cookie):
        return [
            {
                "aweme_id": "7618017056562187554",
                "desc": "你的医保卡，现在能给外地父母用 #医保 #慢病用药",
                "create_time": 1773752460,
                "statistics": {
                    "play_count": 1000,
                    "digg_count": 88,
                    "comment_count": 12,
                    "collect_count": 20,
                    "share_count": 6,
                },
            }
        ]

    async def fake_list_topics_for_publish_matching(_session, *, platform, limit=200):
        assert platform == "douyin"
        return [topic]

    async def fake_upsert_platform_feedback(_session, payload):
        platform_feedback.append(payload)
        return payload

    async def fake_update_topic_feedback(_session, topic_id, payload):
        updates.append((topic_id, payload))
        return None

    async def fake_upsert_bitable_feedback(_client, payloads):
        return {"updated": len(payloads), "errors": []}

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(feedback_collector, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(feedback_collector, "douyin_cookie_exists", lambda: True)
    monkeypatch.setattr(feedback_collector, "load_douyin_cookie", lambda: "sessionid=abc")
    monkeypatch.setattr(feedback_collector, "_fetch_creator_work_list", fake_fetch_work_list)
    monkeypatch.setattr(
        feedback_collector.crud,
        "list_topics_for_publish_matching",
        fake_list_topics_for_publish_matching,
    )
    monkeypatch.setattr(feedback_collector.crud, "upsert_platform_feedback", fake_upsert_platform_feedback)
    monkeypatch.setattr(feedback_collector.crud, "update_topic_feedback", fake_update_topic_feedback)
    monkeypatch.setattr(feedback_collector, "_upsert_bitable_feedback", fake_upsert_bitable_feedback)

    summary = asyncio.run(feedback_collector.collect_douyin_feedback(client=object()))

    assert summary["status"] == "ok"
    assert summary["discovered_videos"] == 1
    assert summary["matched_topics"] == 1
    assert summary["updated_topics"] == 1
    assert summary["bitable_updated"] == 1
    assert platform_feedback[0]["video_id"] == "7618017056562187554"
    assert updates[0][0] == "topic-1"
    assert updates[0][1]["publish_status"] == "published"
    assert updates[0][1]["publish_url"].endswith("/7618017056562187554")


def test_collect_douyin_feedback_matches_alias_terms(monkeypatch):
    topic = SimpleNamespace(
        topic_id="topic-2",
        title="月薪2万，我养不起自己的AI员工",
        publish_match_terms="你的医保卡，现在能给外地父母用\n医保卡外借",
        keywords='["医保","慢病用药"]',
        publish_url=None,
        perf_watch_rate=None,
    )

    async def fake_fetch_work_list(_client, _cookie):
        return [
            {
                "aweme_id": "7618017056562187554",
                "desc": "你的医保卡，现在能给外地父母用 #医保 #慢病用药",
                "create_time": 1773752460,
                "statistics": {
                    "play_count": 1000,
                    "digg_count": 88,
                    "comment_count": 12,
                    "collect_count": 20,
                    "share_count": 6,
                },
            }
        ]

    async def fake_list_topics_for_publish_matching(_session, *, platform, limit=200):
        return [topic]

    async def fake_upsert_platform_feedback(_session, payload):
        return payload

    async def fake_update_topic_feedback(_session, topic_id, payload):
        return None

    async def fake_upsert_bitable_feedback(_client, payloads):
        return {"updated": len(payloads), "errors": []}

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(feedback_collector, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(feedback_collector, "douyin_cookie_exists", lambda: True)
    monkeypatch.setattr(feedback_collector, "load_douyin_cookie", lambda: "sessionid=abc")
    monkeypatch.setattr(feedback_collector, "_fetch_creator_work_list", fake_fetch_work_list)
    monkeypatch.setattr(
        feedback_collector.crud,
        "list_topics_for_publish_matching",
        fake_list_topics_for_publish_matching,
    )
    monkeypatch.setattr(feedback_collector.crud, "upsert_platform_feedback", fake_upsert_platform_feedback)
    monkeypatch.setattr(feedback_collector.crud, "update_topic_feedback", fake_update_topic_feedback)
    monkeypatch.setattr(feedback_collector, "_upsert_bitable_feedback", fake_upsert_bitable_feedback)

    summary = asyncio.run(feedback_collector.collect_douyin_feedback(client=object()))

    assert summary["matched_topics"] == 1
    assert summary["items"][0]["topic_id"] == "topic-2"
    assert summary["items"][0]["match_score"] >= 0.9


def test_collect_xhs_feedback_matches_note_item(monkeypatch):
    topic = SimpleNamespace(
        topic_id="topic-xhs-1",
        title="医保卡别借给别人买药",
        publish_url=None,
        perf_watch_rate=None,
    )
    updates = []
    platform_feedback = []

    def fake_load_xhs_records(limit=50):
        return (
            [
                {
                    "note_id": "abc123ef",
                    "title": "医保卡别借给别人买药",
                    "publish_url": "https://www.xiaohongshu.com/explore/abc123ef",
                    "publish_at": "2026-03-20T08:00:00Z",
                    "play_count": None,
                    "digg_count": 100,
                    "comment_count": 8,
                    "collect_count": 22,
                    "share_count": 3,
                    "collect_rate": None,
                    "raw": {"title": "医保卡别借给别人买药"},
                }
            ],
            "/tmp/xhs.json",
        )

    async def fake_list_topics_for_publish_matching(_session, *, platform, limit=200):
        assert platform == "xiaohongshu"
        return [topic]

    async def fake_upsert_platform_feedback(_session, payload):
        platform_feedback.append(payload)
        return payload

    async def fake_update_topic_feedback(_session, topic_id, payload):
        updates.append((topic_id, payload))
        return None

    async def fake_upsert_bitable_feedback(_client, payloads):
        return {"updated": len(payloads), "errors": []}

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(feedback_collector, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(feedback_collector, "_load_xhs_records", fake_load_xhs_records)
    monkeypatch.setattr(
        feedback_collector.crud,
        "list_topics_for_publish_matching",
        fake_list_topics_for_publish_matching,
    )
    monkeypatch.setattr(feedback_collector.crud, "upsert_platform_feedback", fake_upsert_platform_feedback)
    monkeypatch.setattr(feedback_collector.crud, "update_topic_feedback", fake_update_topic_feedback)
    monkeypatch.setattr(feedback_collector, "_upsert_bitable_feedback", fake_upsert_bitable_feedback)

    summary = asyncio.run(feedback_collector.collect_xhs_feedback(client=object()))

    assert summary["status"] == "ok"
    assert summary["discovered_notes"] == 1
    assert summary["matched_topics"] == 1
    assert summary["bitable_updated"] == 1
    assert platform_feedback[0]["platform"] == "xiaohongshu"
    assert platform_feedback[0]["video_id"] == "abc123ef"
    assert updates[0][0] == "topic-xhs-1"
    assert updates[0][1]["publish_url"].endswith("/abc123ef")
