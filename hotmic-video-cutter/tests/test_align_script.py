#!/usr/bin/env python3
"""
test_align_script.py — align_script.py 的单元测试

测试核心算法：
1. 句子拆分
2. 编辑距离相似度
3. 脚本-转录对齐
4. 无脚本模式n-gram相似度
"""

import sys
import os
import json
import unittest

# 将scripts目录加入模块搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from align_script import (
    levenshtein_distance,
    normalized_edit_similarity,
    split_script_sentences,
    align_script_to_transcript,
    detect_repeats_no_script
)


class TestLevenshteinDistance(unittest.TestCase):
    """测试编辑距离计算。"""

    def test_identical_strings(self):
        """两个完全相同的字符串，编辑距离为0。"""
        self.assertEqual(levenshtein_distance("外泌体", "外泌体"), 0)

    def test_completely_different(self):
        """两个完全不同的字符串。"""
        dist = levenshtein_distance("abc", "xyz")
        self.assertEqual(dist, 3)

    def test_one_empty(self):
        """一个空字符串，编辑距离等于另一个的长度。"""
        self.assertEqual(levenshtein_distance("", "abc"), 3)
        self.assertEqual(levenshtein_distance("abc", ""), 3)

    def test_insertion(self):
        """插入一个字符。"""
        self.assertEqual(levenshtein_distance("大家好", "大家好啊"), 1)

    def test_substitution(self):
        """替换一个字符。"""
        self.assertEqual(levenshtein_distance("外泌体", "外分体"), 1)

    def test_symmetry(self):
        """编辑距离是对称的。"""
        s1, s2 = "大家好我叫小明", "大家好我叫小王"
        self.assertEqual(levenshtein_distance(s1, s2), levenshtein_distance(s2, s1))


class TestNormalizedEditSimilarity(unittest.TestCase):
    """测试归一化编辑相似度。"""

    def test_identical(self):
        """完全相同 → 相似度1.0。"""
        self.assertAlmostEqual(normalized_edit_similarity("外泌体", "外泌体"), 1.0)

    def test_both_empty(self):
        """两个空字符串 → 相似度1.0。"""
        self.assertAlmostEqual(normalized_edit_similarity("", ""), 1.0)

    def test_one_empty(self):
        """一个空字符串 → 相似度0.0。"""
        self.assertAlmostEqual(normalized_edit_similarity("", "abc"), 0.0)

    def test_high_similarity(self):
        """高度相似的句子（只差一个词）。"""
        s1 = "大家好，我今天想和大家聊一聊外泌体的话题"
        s2 = "大家好，我今天想和大家聊一聊外泌体的问题"
        sim = normalized_edit_similarity(s1, s2)
        self.assertGreater(sim, 0.8)

    def test_low_similarity(self):
        """完全不同的句子应该相似度很低。"""
        sim = normalized_edit_similarity("外泌体是纳米囊泡", "今天天气真好啊")
        self.assertLess(sim, 0.3)

    def test_bound_between_0_and_1(self):
        """相似度始终在0到1之间。"""
        pairs = [
            ("abc", "xyz"),
            ("大家好", "大家好吗"),
            ("完全不同的句子", "totally different"),
        ]
        for s1, s2 in pairs:
            sim = normalized_edit_similarity(s1, s2)
            self.assertGreaterEqual(sim, 0.0)
            self.assertLessEqual(sim, 1.0)


class TestSplitScriptSentences(unittest.TestCase):
    """测试脚本句子拆分。"""

    def test_basic_split(self):
        """基本句子拆分（句号分隔）。"""
        script = "大家好。今天我们聊外泌体。外泌体很神奇。"
        sentences = split_script_sentences(script)
        self.assertGreaterEqual(len(sentences), 2)  # 至少包含长句，短句可能被过滤

    def test_mixed_punctuation(self):
        """混合标点符号（句号、问号、感叹号）。"""
        script = "外泌体有效果吗？当然有！科学证据摆在这里。"
        sentences = split_script_sentences(script)
        self.assertGreaterEqual(len(sentences), 3)

    def test_filter_short_sentences(self):
        """过滤单字符句子（纯空白）。"""
        script = "。外泌体是一种纳米级别的细胞外囊泡。\n\n外泌体很神奇。"
        sentences = split_script_sentences(script)
        # 空白/空句子应被过滤
        for sent in sentences:
            self.assertGreaterEqual(len(sent), 2)

    def test_markdown_title_skip(self):
        """跳过Markdown标题行。"""
        script = "# 外泌体科普\n\n大家好，我今天想聊一聊外泌体。\n\n## 什么是外泌体\n\n外泌体是纳米囊泡。"
        sentences = split_script_sentences(script)
        # 标题行应被跳过
        for sent in sentences:
            self.assertFalse(sent.startswith('#'))

    def test_newline_split(self):
        """换行符也是分隔符。"""
        script = "第一句话在这里\n第二句话在这里\n第三句话在这里"
        sentences = split_script_sentences(script)
        self.assertGreaterEqual(len(sentences), 3)


class TestAlignScriptToTranscript(unittest.TestCase):
    """测试脚本-转录对齐。"""

    def setUp(self):
        """加载示例数据。"""
        sample_data_dir = os.path.join(os.path.dirname(__file__), 'sample_data')
        with open(os.path.join(sample_data_dir, 'sample_transcript.json'), 'r', encoding='utf-8') as f:
            self.transcript = json.load(f)
        self.segments = self.transcript['segments']

        with open(os.path.join(sample_data_dir, 'sample_script.md'), 'r', encoding='utf-8') as f:
            script_text = f.read()
        self.script_sentences = split_script_sentences(script_text)

    def test_alignment_returns_list(self):
        """对齐结果应为列表。"""
        alignment = align_script_to_transcript(self.script_sentences, self.segments)
        self.assertIsInstance(alignment, list)

    def test_alignment_covers_all_sentences(self):
        """对齐结果应涵盖所有脚本句子。"""
        alignment = align_script_to_transcript(self.script_sentences, self.segments)
        self.assertEqual(len(alignment), len(self.script_sentences))

    def test_repeated_sentence_detected(self):
        """重复录制的句子应被检测到（is_repeated=True）。"""
        alignment = align_script_to_transcript(self.script_sentences, self.segments, threshold=0.4)
        repeated = [a for a in alignment if a["is_repeated"]]
        # 示例数据中"大家好...话题"录了两遍，应该被检测到
        self.assertGreater(len(repeated), 0, "应检测到至少一个重复句子")

    def test_similarity_scores_in_range(self):
        """相似度分数应在0到1之间。"""
        alignment = align_script_to_transcript(self.script_sentences, self.segments)
        for entry in alignment:
            for match in entry["matched_segments"]:
                self.assertGreaterEqual(match["similarity"], 0.0)
                self.assertLessEqual(match["similarity"], 1.0)

    def test_alignment_structure(self):
        """对齐结果每项应包含必要字段。"""
        alignment = align_script_to_transcript(self.script_sentences, self.segments)
        for entry in alignment:
            self.assertIn("sentence_idx", entry)
            self.assertIn("script_sentence", entry)
            self.assertIn("matched_segments", entry)
            self.assertIn("is_repeated", entry)


class TestDetectRepeatsNoScript(unittest.TestCase):
    """测试无脚本模式的n-gram相似度重复检测。"""

    def test_identical_adjacent_detected(self):
        """相邻完全相同的segment应被检测为重复。"""
        segments = [
            {"id": 0, "start": 0.0, "end": 3.0, "text": "大家好，我今天想和大家聊一聊外泌体的话题。"},
            {"id": 1, "start": 4.0, "end": 7.0, "text": "大家好，我今天想和大家聊一聊外泌体的话题。"},
            {"id": 2, "start": 8.0, "end": 12.0, "text": "外泌体是纳米级别的细胞外囊泡。"}
        ]
        pairs = detect_repeats_no_script(segments, threshold=0.8)
        self.assertGreater(len(pairs), 0)
        # 第一对应该被检测到
        self.assertEqual(pairs[0]["seg_a"], 0)
        self.assertEqual(pairs[0]["seg_b"], 1)

    def test_different_segments_not_detected(self):
        """完全不同的相邻segment不应被检测为重复。"""
        segments = [
            {"id": 0, "start": 0.0, "end": 3.0, "text": "大家好，今天聊外泌体。"},
            {"id": 1, "start": 4.0, "end": 7.0, "text": "苹果是一种水果，含有丰富的维生素。"},
            {"id": 2, "start": 8.0, "end": 12.0, "text": "天气今天很好，适合出门。"}
        ]
        pairs = detect_repeats_no_script(segments, threshold=0.85)
        self.assertEqual(len(pairs), 0)

    def test_similarity_score_in_range(self):
        """相似度分数应在0到1之间。"""
        segments = [
            {"id": 0, "start": 0.0, "end": 3.0, "text": "外泌体很神奇，功效显著。"},
            {"id": 1, "start": 4.0, "end": 7.0, "text": "外泌体很神奇，功效明显。"},
        ]
        pairs = detect_repeats_no_script(segments, threshold=0.5)
        for pair in pairs:
            self.assertGreaterEqual(pair["similarity"], 0.0)
            self.assertLessEqual(pair["similarity"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
