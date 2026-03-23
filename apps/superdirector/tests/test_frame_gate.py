from __future__ import annotations

from pipeline.frame_gate import frame_quality_gate
from pipeline.pipeline import _apply_frame_quality_gate


def test_frame_quality_gate_passes_valid_douyin_frame():
    passed, reason = frame_quality_gate(
        {
            "platform_priority": "douyin",
            "frame": {
                "hook": "进了医保，为什么医院还是开不出来？",
                "outline": [
                    "先讲大家最常见的误解在哪里",
                    "再拆医院端真正卡住的几道门",
                    "解释为什么患者会以为是药价问题",
                    "最后给家属一个判断和转发理由",
                ],
                "cta": "转给家里负责报销的人",
            },
        }
    )

    assert passed is True
    assert reason == "通过"


def test_frame_quality_gate_rejects_long_hook():
    passed, reason = frame_quality_gate(
        {
            "platform_priority": "douyin",
            "frame": {
                "hook": "这是一个明显超过抖音限制而且故意写得特别特别长的开头钩子方便测试",
                "outline": [
                    "第一条已经满足最短长度要求方便继续测试",
                    "第二条也满足最短长度要求确保只命中 hook",
                    "第三条继续满足长度要求避免混淆原因",
                    "第四条同样满足长度要求保持结构完整",
                ],
                "cta": "去转发",
            },
        }
    )

    assert passed is False
    assert "hook 过长" in reason


def test_frame_quality_gate_rejects_redline_hook():
    passed, reason = frame_quality_gate(
        {
            "platform_priority": "shipinhao",
            "frame": {
                "hook": "你可能是吃错药了，赶紧换这个方案",
                "outline": [
                    "先解释为什么这种说法本身就有风险",
                    "再说明普通人最容易被什么话术带偏",
                    "补充真正应该找谁判断和核对",
                    "最后提醒别把短视频当处方单",
                ],
                "cta": "发给家里爱转药方的人",
            },
        }
    )

    assert passed is False
    assert "C01" in reason


def test_apply_frame_quality_gate_marks_rejected_topic():
    topics = [
        {
            "topic_id": "ok",
            "platform_priority": "douyin",
            "frame": {
                "hook": "315点名后，为什么外泌体还在收智商税？",
                "outline": [
                    "先讲这类概念包装为什么特别容易出圈",
                    "再拆商家最爱利用的几个心理暗示",
                    "补充普通人判断是否夸大的简单方法",
                    "最后给一个可转发的避坑结论",
                ],
                "cta": "转给家里爱看养生内容的人",
            },
        },
        {
            "topic_id": "bad",
            "platform_priority": "douyin",
            "frame": {
                "hook": "你可能是已经踩坑了",
                "outline": [
                    "第一条也够长避免混入 outline 问题",
                    "第二条也够长避免混入 outline 问题",
                    "第三条也够长避免混入 outline 问题",
                    "第四条也够长避免混入 outline 问题",
                ],
                "cta": "转发",
            },
        },
    ]

    gated = _apply_frame_quality_gate(topics)

    assert gated[0]["frame_status"] == "passed"
    assert gated[0]["frame_rejection_reason"] is None
    assert gated[1]["frame_status"] == "rejected"
    assert gated[1]["frame_rejection_reason"]
