#!/usr/bin/env python3
"""
test_detect_repeats.py — detect_repeats.py 的单元测试

测试：
1. 流利度分数计算
2. 综合评分（文本准确度 + 流利度）
3. 有脚本模式的选优逻辑
4. 无脚本模式的选优逻辑（保留更长的segment）
"""

import sys
import os
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from detect_repeats import compute_fluency_score, score_segment, decide_with_script, decide_no_script


class TestFluencyScore(unittest.TestCase):
    """测试流利度分数计算。"""

    def setUp(self):
        """构建测试用的词级时间戳数据。"""
        # 流利的词：词间隔均匀，无明显停顿
        self.fluent_words = [
            {"word": "外泌体", "start": 0.0, "end": 0.8},
            {"word": "是", "start": 0.85, "end": 1.0},
            {"word": "纳米", "start": 1.05, "end": 1.5},
            {"word": "囊泡", "start": 1.55, "end": 2.0},
        ]
        # 不流利的词：有明显停顿
        self.disfluent_words = [
            {"word": "外泌体", "start": 0.0, "end": 0.8},
            {"word": "是", "start": 1.9, "end": 2.1},   # 停顿 1.1s
            {"word": "纳米", "start": 3.5, "end": 4.0},  # 停顿 1.4s
            {"word": "囊泡", "start": 4.05, "end": 4.5},
        ]

    def test_fluent_higher_than_disfluent(self):
        """流利录音的流利度分数应高于不流利的录音。"""
        seg = {"start": 0.0, "end": 2.0}
        fluent_score = compute_fluency_score(seg, self.fluent_words)
        disfluent_score = compute_fluency_score(seg, self.disfluent_words)
        self.assertGreater(fluent_score, disfluent_score)

    def test_score_in_range(self):
        """流利度分数应在0到1之间。"""
        seg = {"start": 0.0, "end": 2.0}
        score = compute_fluency_score(seg, self.fluent_words)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_single_word_returns_default(self):
        """单个词时，返回默认值0.5。"""
        seg = {"start": 0.0, "end": 1.0}
        words = [{"word": "外泌体", "start": 0.0, "end": 1.0}]
        score = compute_fluency_score(seg, words)
        self.assertAlmostEqual(score, 0.5)

    def test_no_words_returns_default(self):
        """无词时，返回默认值0.5。"""
        seg = {"start": 0.0, "end": 2.0}
        score = compute_fluency_score(seg, [])
        self.assertAlmostEqual(score, 0.5)


class TestScoreSegment(unittest.TestCase):
    """测试综合评分计算。"""

    def setUp(self):
        self.script_sentence = "外泌体是一种纳米级别的细胞外囊泡"
        self.words = [
            {"word": "外泌体", "start": 0.0, "end": 0.8},
            {"word": "是", "start": 0.85, "end": 1.0},
            {"word": "纳米", "start": 1.05, "end": 1.5},
        ]

    def test_exact_match_high_score(self):
        """与脚本完全匹配的segment综合分应较高。"""
        seg = {"start": 0.0, "end": 5.0}
        score = score_segment(self.script_sentence, self.script_sentence, seg, self.words)
        self.assertGreater(score, 0.7)

    def test_mismatch_lower_score(self):
        """与脚本差异较大的segment分应低于完全匹配的。"""
        seg = {"start": 0.0, "end": 5.0}
        exact_score = score_segment(self.script_sentence, self.script_sentence, seg, self.words)
        different_text = "今天天气很好，我们去公园玩"
        different_score = score_segment(different_text, self.script_sentence, seg, self.words)
        self.assertGreater(exact_score, different_score)

    def test_score_in_range(self):
        """综合分应在0到1之间。"""
        seg = {"start": 0.0, "end": 5.0}
        score = score_segment(self.script_sentence, self.script_sentence, seg, self.words)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestDecideWithScript(unittest.TestCase):
    """测试有脚本模式的选优决策。"""

    def setUp(self):
        """构建包含重复段落的alignment数据。"""
        self.alignment = {
            "mode": "with_script",
            "segments": [
                {"id": 0, "start": 0.0, "end": 5.2, "text": "大家好，我今天想聊外泌体的话题。", "avg_logprob": -0.18, "no_speech_prob": 0.01},
                {"id": 1, "start": 6.5, "end": 11.8, "text": "大家好，我今天想聊外泌体的话题。", "avg_logprob": -0.22, "no_speech_prob": 0.01},
                {"id": 2, "start": 12.0, "end": 18.0, "text": "外泌体是纳米囊泡。", "avg_logprob": -0.15, "no_speech_prob": 0.01},
            ],
            "alignment": [
                {
                    "sentence_idx": 0,
                    "script_sentence": "大家好，我今天想聊外泌体的话题。",
                    "is_repeated": True,
                    "matched_segments": [
                        {"seg_idx": 0, "start": 0.0, "end": 5.2, "text": "大家好，我今天想聊外泌体的话题。", "similarity": 0.95},
                        {"seg_idx": 1, "start": 6.5, "end": 11.8, "text": "大家好，我今天想聊外泌体的话题。", "similarity": 0.92},
                    ]
                },
                {
                    "sentence_idx": 1,
                    "script_sentence": "外泌体是纳米囊泡。",
                    "is_repeated": False,
                    "matched_segments": [
                        {"seg_idx": 2, "start": 12.0, "end": 18.0, "text": "外泌体是纳米囊泡。", "similarity": 0.98},
                    ]
                }
            ]
        }
        self.words = []

    def test_repeated_group_has_one_keep(self):
        """重复组中应只有一个'keep'决策。"""
        decisions = decide_with_script(self.alignment, self.words)
        keep_decisions = [d for d in decisions if d["action"] == "keep" and
                          d["script_sentence"] == "大家好，我今天想聊外泌体的话题。"]
        delete_decisions = [d for d in decisions if d["action"] == "delete"]
        self.assertEqual(len(keep_decisions), 1)
        self.assertGreater(len(delete_decisions), 0)

    def test_non_repeated_is_kept(self):
        """非重复段落应直接保留。"""
        decisions = decide_with_script(self.alignment, self.words)
        unique_segment = next(
            (d for d in decisions if d.get("script_sentence") == "外泌体是纳米囊泡。"),
            None
        )
        self.assertIsNotNone(unique_segment)
        self.assertEqual(unique_segment["action"], "keep")

    def test_decisions_sorted_by_time(self):
        """决策应按时间轴排序。"""
        decisions = decide_with_script(self.alignment, self.words)
        starts = [d["segment_start"] for d in decisions]
        self.assertEqual(starts, sorted(starts))


class TestDecideNoScript(unittest.TestCase):
    """测试无脚本模式的选优决策（保留更长版本）。"""

    def test_longer_segment_kept(self):
        """两个相似segment中，应保留时长更长的那个。"""
        segments = [
            {"id": 0, "start": 0.0, "end": 3.0, "text": "外泌体是纳米囊泡。"},   # 时长3s
            {"id": 1, "start": 4.0, "end": 9.0, "text": "外泌体是纳米囊泡。"},   # 时长5s（更长）
        ]
        alignment = {
            "similar_pairs": [
                {"seg_a": 0, "seg_b": 1, "similarity": 0.95, "text_a": segments[0]["text"], "text_b": segments[1]["text"]}
            ]
        }
        decisions = decide_no_script(alignment, segments, [])

        # 找到每个segment的决策
        dec_0 = next(d for d in decisions if abs(d["segment_start"] - 0.0) < 0.01)
        dec_1 = next(d for d in decisions if abs(d["segment_start"] - 4.0) < 0.01)

        # 时长5s的segment（idx=1）应该被保留
        self.assertEqual(dec_0["action"], "delete")
        self.assertEqual(dec_1["action"], "keep")

    def test_no_repeats_all_kept(self):
        """没有重复时，所有segment都应保留。"""
        segments = [
            {"id": 0, "start": 0.0, "end": 3.0, "text": "内容A"},
            {"id": 1, "start": 4.0, "end": 7.0, "text": "内容B"},
        ]
        alignment = {"similar_pairs": []}
        decisions = decide_no_script(alignment, segments, [])
        self.assertTrue(all(d["action"] == "keep" for d in decisions))


if __name__ == "__main__":
    unittest.main(verbosity=2)
