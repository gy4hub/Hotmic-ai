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
    assert framed[0]["frame"]["hook"].startswith("MOCK:")
    assert framed[0]["frame"]["cta"] == "转给家族群里关心药费的人"


def test_generate_frames_aggregates_usage_and_errors(monkeypatch):
    calls = []

    async def fake_frame_with_qwen(_client, topic):
        calls.append(topic["topic_id"])
        if topic["topic_id"] == "bad":
            raise RuntimeError("boom")
        return (
            {**topic, "frame": {"hook": "h", "outline": ["a", "b", "c", "d"], "cta": "go"}},
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

    assert calls == ["ok", "bad"]
    assert len(errors) == 1
    assert "Frame generation failed for 题目2: boom" in errors[0]
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 5
    assert framed[1]["status"] == "failed"
    assert errors[0] in framed[1]["errors"]

