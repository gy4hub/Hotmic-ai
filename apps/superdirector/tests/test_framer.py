from __future__ import annotations

import asyncio

from pipeline import framer


def test_generate_frames_returns_mock_payload(monkeypatch):
    monkeypatch.setattr(framer, "is_mock_mode", lambda: True)

    framed, errors, usage = asyncio.run(
        framer.generate_frames(
            ext_client=object(),
            int_client=object(),
            topics=[{"topic_id": "t1", "title": "医保卡别乱借", "platform_priority": "douyin"}],
        )
    )

    assert errors == []
    assert usage == {}
    assert framed[0]["frame_tier"] == "full"
    assert framed[0]["frame"]["hook"].startswith("MOCK:")
    assert framed[0]["frame"]["cta"] == "转给家族群里关心药费的人"


def test_generate_frames_aggregates_usage_and_errors(monkeypatch):
    calls = []

    async def fake_frame_with_qwen(_client, topic, *, lite=False):
        calls.append(f"{topic['topic_id']}:{lite}")
        if topic["topic_id"] == "bad":
            raise RuntimeError("boom")
        return (
            {
                **topic,
                "frame_tier": "lite" if lite else "full",
                "frame": {"hook": "hook text", "outline": ["outline aa", "outline bb", "outline cc", "outline dd"], "cta": "go"},
            },
            {
                "provider": "qwen",
                "model": "qwen-plus",
                "endpoint": "chat.completions",
                "input_tokens": 10,
                "output_tokens": 5,
            },
        )

    monkeypatch.setattr(framer, "is_mock_mode", lambda: False)
    monkeypatch.setattr(framer, "QWEN_API_KEY", "token")
    monkeypatch.setattr(framer, "_frame_with_qwen", fake_frame_with_qwen)

    framed, errors, usage = asyncio.run(
        framer.generate_frames(
            ext_client=object(),
            int_client=object(),
            topics=[
                {"topic_id": "ok", "title": "题目1", "platform_priority": "douyin"},
                {"topic_id": "bad", "title": "题目2", "platform_priority": "douyin"},
            ],
            )
        )

    assert calls == ["ok:False", "bad:False", "bad:True"]
    assert len(errors) == 1
    assert "Frame generation failed for 题目2: generation_failed" in errors[0]
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 5
    assert framed[1]["status"] == "failed"
    assert framed[1]["frame_status"] == "rejected"
    assert framed[1]["frame_rejection_reason"] == "generation_failed"
    assert "Frame generation failed: boom" in framed[1]["errors"][0]


def test_frame_topic_falls_back_to_lite_when_full_frame_rejected(monkeypatch):
    async def fake_frame_with_qwen(_client, topic, *, lite=False):
        if not lite:
            return (
                {
                    **topic,
                    "frame_tier": "full",
                    "frame": {
                        "hook": "这是一个明显超过抖音限制而且故意写得特别特别长的开头钩子方便测试",
                        "outline": [
                            "第一条已经满足最短长度要求方便继续测试",
                            "第二条也满足最短长度要求确保只命中 hook",
                            "第三条继续满足长度要求避免混淆原因",
                            "第四条同样满足长度要求保持结构完整",
                        ],
                        "cta": "转发",
                    },
                },
                {"provider": "qwen", "model": "qwen-plus", "endpoint": "chat.completions", "input_tokens": 8, "output_tokens": 4},
            )
        return (
            {
                **topic,
                "frame_tier": "lite",
                "frame": {
                    "hook": "医保进了，为啥还难开？",
                    "outline": [
                        "先讲患者最常见误解",
                        "再拆医院端卡点",
                        "最后给家属判断法",
                    ],
                    "cta": "",
                },
            },
            {"provider": "qwen", "model": "qwen-plus", "endpoint": "chat.completions", "input_tokens": 5, "output_tokens": 3},
        )

    monkeypatch.setattr(framer, "QWEN_API_KEY", "token")
    monkeypatch.setattr(framer, "_frame_with_qwen", fake_frame_with_qwen)

    framed_topic, usage = asyncio.run(
        framer._frame_topic(
            ext_client=object(),
            int_client=object(),
            topic={"topic_id": "t1", "title": "医保卡别乱借", "platform_priority": "douyin"},
        )
    )

    assert framed_topic["frame_tier"] == "lite"
    assert framed_topic["frame_status"] == "passed"
    assert usage["input_tokens"] == 13
    assert usage["output_tokens"] == 7
