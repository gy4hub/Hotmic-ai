import asyncio
from types import SimpleNamespace

from pipeline import feedback
from pipeline.feedback import _normalize_feedback, _has_feedback, _infer_feedback_platform


def test_feedback_detects_populated_fields():
    fields = {"topic_id": "t1", "publish_status": "published", "perf_comments": 12}
    assert _has_feedback(fields) is True


def test_feedback_normalize_casts_numbers():
    feedback = _normalize_feedback(
        {
            "publish_status": "published",
            "publish_url": "https://example.com",
            "publish_at": "2026-03-16",
            "perf_watch_rate": "43.5",
            "perf_favorite_rate": "6.8",
            "perf_comments": "12",
            "perf_shares": "3",
            "creator_notes": "comments look strong",
            "review_status": "reviewed",
        }
    )
    assert feedback["publish_status"] == "published"
    assert feedback["perf_watch_rate"] == 43.5
    assert feedback["perf_comments"] == 12
    assert feedback["review_status"] == "reviewed"


def test_infer_feedback_platform_from_url():
    assert _infer_feedback_platform("https://channels.weixin.qq.com/test", None) == "shipinhao"
    assert _infer_feedback_platform("https://www.xiaohongshu.com/explore/abc123", None) == "xiaohongshu"
    assert _infer_feedback_platform("https://www.douyin.com/video/7618017056562187554", None) == "douyin"


def test_feedback_sync_upserts_platform_feedback(monkeypatch):
    records = [
        {
            "fields": {
                "topic_id": "t1",
                "publish_status": "published",
                "publish_url": "https://channels.weixin.qq.com/example/123",
                "publish_at": "2026-03-22T20:00:00Z",
                "perf_watch_rate": "42",
                "perf_comments": "6",
                "perf_shares": "2",
            }
        }
    ]
    upserts = []
    replaced = []

    async def fake_list_topic_records(_client):
        return records

    async def fake_update_topic_feedback(_session, topic_key, payload):
        assert topic_key == "t1"
        return SimpleNamespace(id=9, topic_id="t1", platform_priority="shipinhao")

    async def fake_upsert_platform_feedback(_session, payload):
        upserts.append(payload)
        return payload

    async def fake_replace_feedback_score_details(_session, topic_db_id, metrics, *, platform, weight_version="feedback_v1"):
        replaced.append((topic_db_id, metrics, platform))

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(feedback, "_list_topic_records", fake_list_topic_records)
    monkeypatch.setattr(feedback, "feedback_sync_enabled", lambda: True)
    monkeypatch.setattr(feedback.crud, "update_topic_feedback", fake_update_topic_feedback)
    monkeypatch.setattr(feedback.crud, "upsert_platform_feedback", fake_upsert_platform_feedback)
    monkeypatch.setattr(feedback.crud, "replace_feedback_score_details", fake_replace_feedback_score_details)
    monkeypatch.setattr(feedback, "AsyncSessionLocal", lambda: DummySession())

    summary = asyncio.run(feedback.sync_feedback_from_bitable(client=object()))

    assert summary["updated"] == 1
    assert upserts[0]["platform"] == "shipinhao"
    assert upserts[0]["publish_url"].startswith("https://channels.weixin.qq.com/")
    assert upserts[0]["completion_rate"] == 42.0
    assert replaced[0][2] == "shipinhao"
