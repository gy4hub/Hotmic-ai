from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pipeline import editorial
from tools import api_routes


class DummyRequest:
    def __init__(self, payload=None, ext_client=None):
        self._payload = payload or {}
        self.app = SimpleNamespace(state=SimpleNamespace(ext_client=ext_client or object()))

    async def json(self):
        return self._payload


def test_build_editorial_prompt_section_uses_casey_profile(monkeypatch):
    monkeypatch.setattr(
        editorial,
        "load_casey_profile",
        lambda: {
            "display_name": "Casey",
            "dual_audience_model": {
                "decision_layer": {
                    "label": "李姐Plus",
                    "who": "更偏收藏导向的家庭决策者",
                    "expected_action": "收藏转发",
                },
                "spread_layer": {
                    "label": "张阿姨Plus",
                    "who": "更愿意在家族群传播的人",
                    "expected_action": "转到家族群",
                },
            },
        },
    )

    prompt = editorial.build_editorial_prompt_section()

    assert "Casey能不能用政策、定价、供应链" in prompt
    assert "李姐Plus（更偏收藏导向的家庭决策者）" in prompt
    assert "张阿姨Plus（更愿意在家族群传播的人）" in prompt
    assert "李姐Plus会不会收藏转发，张阿姨Plus会不会转到家族群" in prompt


def test_build_hotmic_script_payload_maps_topic_to_hotmic_input(monkeypatch):
    monkeypatch.setattr(
        api_routes,
        "load_casey_profile",
        lambda: {"account_id": "casey", "display_name": "添爸"},
    )
    monkeypatch.setattr(
        api_routes,
        "_load_high_confidence_style_rules",
        lambda *args, **kwargs: [{"rule": "标题更口语化", "confidence": 0.88}],
    )
    row = SimpleNamespace(
        topic_id="topic-1",
        title="进了医保，为什么医院还是开不出来？",
        summary="核心矛盾不是药价，而是进院和支付路径。",
        keywords='["医保","进院难"]',
        url="https://example.com/a",
        search_sources='[{"url":"https://example.com/b"}]',
        source="nmpa_news",
        content_role="save",
        platform_priority="shipinhao",
        frame_json='{"hook":"很多人以为进医保就能开到药","outline":["误解在哪","真实卡点","谁最受影响","怎么判断"],"cta":"转给家里负责报销的人"}',
        raw_snippet="患者明明看到进医保，却还是在医院开不到。",
        compliance_risk="low",
        actionability_risk="low",
    )

    payload = api_routes._build_hotmic_script_payload(row)

    assert payload["content_type"] == "collect"
    assert payload["platform_priority"] == "wechat_video"
    assert payload["topic"]["keywords"] == ["医保", "进院难"]
    assert payload["topic"]["source_urls"] == ["https://example.com/a", "https://example.com/b"]
    assert payload["frame"]["hook"] == "很多人以为进医保就能开到药"
    assert payload["style_patch"][0]["rule"] == "标题更口语化"
    assert payload["persona_profile"]["account_id"] == "casey"
    assert payload["compliance_context"]["source_grade"] == "A"
    assert payload["compliance_context"]["verified_facts"]


def test_build_hotmic_script_payload_preserves_xiaohongshu_platform(monkeypatch):
    monkeypatch.setattr(
        api_routes,
        "load_casey_profile",
        lambda: {"account_id": "casey", "display_name": "添爸"},
    )
    monkeypatch.setattr(api_routes, "_load_high_confidence_style_rules", lambda *args, **kwargs: [])
    row = SimpleNamespace(
        topic_id="topic-xhs",
        title="医保卡别借给别人买药",
        summary="小红书平台也需要保留平台语义。",
        keywords='["医保卡"]',
        url="https://example.com/xhs",
        search_sources="[]",
        source="wechat_rss",
        content_role="spread",
        platform_priority="xiaohongshu",
        frame_json='{"hook":"别把医保卡借出去","outline":["为什么","风险在哪","如何识别","结论"],"cta":"转给家里人"}',
        raw_snippet="医保卡外借会留下购药记录。",
        compliance_risk="low",
        actionability_risk="low",
    )

    payload = api_routes._build_hotmic_script_payload(row)

    assert payload["platform_priority"] == "xiaohongshu"


def test_topics_publish_confirm_updates_topic_and_bitable(monkeypatch):
    updated_payloads = []
    bitable_updates = []

    row = SimpleNamespace(
        id=1,
        topic_id="topic-1",
        date="2026-03-23",
        title="标题",
        score_total=4.8,
        editorial_priority_score=5.1,
        platform_priority="douyin",
        summary="摘要",
        source="wechat_rss",
        timestamp="2026-03-23T12:00:00Z",
        raw_snippet="片段",
        keywords='["医保"]',
        url="https://example.com",
        topic_line_primary="public_issue",
        topic_line_secondary=None,
        line_confidence=0.9,
        content_role="spread",
        creator_fit="strong",
        li_jie_value="save",
        zhang_auntie_value="forward",
        audience_core="family_decision_maker",
        compliance_risk="low",
        actionability_risk="low",
        topic_cluster="医保进院难",
        reject_type="none",
        rejection_reason=None,
        timeliness_window="burst",
        platform_fit="both",
        decision_impact_level="high",
        selection_rank_reason="优先",
        status="ok",
        errors_json="[]",
        creator_ops=None,
        publish_status=None,
        publish_url=None,
        publish_at=None,
    )

    async def fake_get_topic_by_topic_id(_session, topic_id):
        assert topic_id == "topic-1"
        return row

    async def fake_update_topic_feedback(_session, topic_id, payload):
        updated_payloads.append((topic_id, payload))
        for key, value in payload.items():
            setattr(row, key, value)
        return row

    async def fake_upsert_bitable_feedback(_client, payloads):
        bitable_updates.extend(payloads)
        return {"updated": len(payloads), "errors": []}

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(api_routes.crud, "get_topic_by_topic_id", fake_get_topic_by_topic_id)
    monkeypatch.setattr(api_routes.crud, "update_topic_feedback", fake_update_topic_feedback)
    monkeypatch.setattr(api_routes, "_upsert_bitable_feedback", fake_upsert_bitable_feedback)
    monkeypatch.setattr(api_routes, "AsyncSessionLocal", lambda: DummySession())

    result = asyncio.run(
        api_routes.topics_publish_confirm(
            "topic-1",
            DummyRequest(
                {
                    "platform": "wechat_video",
                    "publish_url": "https://channels.weixin.qq.com/example",
                    "publish_at": "2026-03-23T20:00:00+08:00",
                    "script_path": "/tmp/script.md",
                }
            ),
        )
    )

    assert updated_payloads[0][1]["publish_status"] == "published"
    assert updated_payloads[0][1]["platform_priority"] == "shipinhao"
    assert bitable_updates[0]["publish_url"] == "https://channels.weixin.qq.com/example"
    assert result["script_path"] == "/tmp/script.md"
    assert result["topic"]["publish_status"] == "published"


def test_topics_publish_confirm_preserves_xiaohongshu_platform(monkeypatch):
    updated_payloads = []

    row = SimpleNamespace(
        id=9,
        topic_id="topic-xhs-1",
        date="2026-03-23",
        title="小红书标题",
        score_total=4.2,
        editorial_priority_score=4.7,
        platform_priority="xiaohongshu",
        summary="摘要",
        source="wechat_rss",
        timestamp="2026-03-23T12:00:00Z",
        raw_snippet="片段",
        keywords='["医保"]',
        url="https://example.com",
        topic_line_primary="family_anxiety",
        topic_line_secondary=None,
        line_confidence=0.8,
        content_role="save",
        creator_fit="strong",
        li_jie_value="save",
        zhang_auntie_value="watch",
        audience_core="family_decision_maker",
        compliance_risk="low",
        actionability_risk="low",
        topic_cluster="家庭药箱",
        reject_type="none",
        rejection_reason=None,
        timeliness_window="evergreen",
        platform_fit="xiaohongshu",
        decision_impact_level="medium",
        selection_rank_reason="适合种草避坑",
        status="ok",
        errors_json="[]",
        creator_ops=None,
        publish_status=None,
        publish_url=None,
        publish_at=None,
    )

    async def fake_get_topic_by_topic_id(_session, topic_id):
        assert topic_id == "topic-xhs-1"
        return row

    async def fake_update_topic_feedback(_session, topic_id, payload):
        updated_payloads.append((topic_id, payload))
        for key, value in payload.items():
            setattr(row, key, value)
        return row

    async def fake_upsert_bitable_feedback(_client, payloads):
        return {"updated": len(payloads), "errors": []}

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(api_routes.crud, "get_topic_by_topic_id", fake_get_topic_by_topic_id)
    monkeypatch.setattr(api_routes.crud, "update_topic_feedback", fake_update_topic_feedback)
    monkeypatch.setattr(api_routes, "_upsert_bitable_feedback", fake_upsert_bitable_feedback)
    monkeypatch.setattr(api_routes, "AsyncSessionLocal", lambda: DummySession())

    result = asyncio.run(
        api_routes.topics_publish_confirm(
            "topic-xhs-1",
            DummyRequest(
                {
                    "platform": "xiaohongshu",
                    "publish_url": "https://www.xiaohongshu.com/explore/abc123",
                    "publish_at": "2026-03-23T20:00:00+08:00",
                }
            ),
        )
    )

    assert updated_payloads[0][1]["platform_priority"] == "xiaohongshu"
    assert result["topic"]["platform_priority"] == "xiaohongshu"


def test_topics_today_create_script_uses_ranked_topic(monkeypatch):
    row = SimpleNamespace(
        id=2,
        topic_id="topic-2",
        date="2026-03-23",
        title="第2条标题",
        score_total=4.6,
        editorial_priority_score=4.9,
        platform_priority="douyin",
        summary="适合直接转成创作输入",
        source="wechat_rss",
        timestamp="2026-03-23T09:00:00Z",
        raw_snippet="这是原始片段",
        keywords='["外泌体","315"]',
        search_sources="[]",
        url="https://example.com/2",
        topic_line_primary="consumer_scam",
        topic_line_secondary=None,
        line_confidence=0.86,
        content_role="spread",
        creator_fit="strong",
        li_jie_value="click",
        zhang_auntie_value="forward",
        audience_core="health_consumer",
        compliance_risk="low",
        actionability_risk="low",
        topic_cluster="抗衰骗局",
        reject_type="none",
        rejection_reason=None,
        timeliness_window="burst",
        platform_fit="douyin",
        decision_impact_level="medium",
        selection_rank_reason="传播潜力高",
        status="ok",
        errors_json="[]",
        frame_json='{"hook":"315点名后为什么还会有人信","outline":["概念包装","为什么容易上头","普通人怎么识别","结论"],"cta":"转给家里爱看养生内容的人"}',
        publish_status=None,
        publish_url=None,
        publish_at=None,
    )

    monkeypatch.setattr(
        api_routes,
        "_resolve_today_ranked_topic",
        lambda rank: asyncio.sleep(0, result=(SimpleNamespace(id=101), row)),
    )
    monkeypatch.setattr(
        api_routes,
        "load_casey_profile",
        lambda: {"account_id": "casey", "display_name": "添爸"},
    )
    monkeypatch.setattr(
        api_routes,
        "_load_high_confidence_style_rules",
        lambda *args, **kwargs: [{"rule": "更像真人口播", "confidence": 0.8}],
    )
    monkeypatch.setattr(api_routes, "_build_hotmic_launch_command", lambda: "python run_hotmic.py")

    result = asyncio.run(
        api_routes.topics_today_create_script(
            2,
            DummyRequest({"platform": "wechat_video"}),
        )
    )

    assert result["rank"] == 2
    assert result["topic"]["topic_id"] == "topic-2"
    assert result["hotmic_input"]["platform_priority"] == "wechat_video"
    assert result["hotmic_input"]["style_patch"][0]["rule"] == "更像真人口播"
    assert "今日第 2 条" in result["telegram_message"]
    assert "python run_hotmic.py" in result["telegram_message"]


def test_topics_today_publish_confirm_uses_ranked_topic(monkeypatch):
    called = {}
    row = SimpleNamespace(topic_id="topic-3")

    monkeypatch.setattr(
        api_routes,
        "_resolve_today_ranked_topic",
        lambda rank: asyncio.sleep(0, result=(SimpleNamespace(id=102), row)),
    )

    async def fake_confirm_publish_for_topic(*, topic_id, payload, ext_client):
        called["topic_id"] = topic_id
        called["payload"] = payload
        called["ext_client"] = ext_client
        return {
            "topic": {
                "topic_id": topic_id,
                "title": "第3条标题",
                "platform_priority": "douyin",
                "publish_status": "published",
                "publish_url": payload["publish_url"],
                "publish_at": payload["publish_at"],
            },
            "script_path": payload.get("script_path"),
            "bitable_sync": {"updated": 1, "errors": []},
        }

    monkeypatch.setattr(api_routes, "_confirm_publish_for_topic", fake_confirm_publish_for_topic)

    result = asyncio.run(
        api_routes.topics_today_publish_confirm(
            3,
            DummyRequest(
                {
                    "platform": "douyin",
                    "publish_url": "https://douyin.com/video/123",
                    "publish_at": "2026-03-23T21:00:00+08:00",
                    "script_path": "/tmp/topic-3.md",
                },
                ext_client="client-x",
            ),
        )
    )

    assert called["topic_id"] == "topic-3"
    assert called["payload"]["publish_url"] == "https://douyin.com/video/123"
    assert called["ext_client"] == "client-x"
    assert result["rank"] == 3
    assert result["topic"]["publish_status"] == "published"
    assert "今日第 3 条" in result["telegram_message"]
    assert "/tmp/topic-3.md" in result["telegram_message"]
