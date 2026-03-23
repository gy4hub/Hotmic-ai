#!/usr/bin/env python3
"""
test_review_engine.py — review-engine 核心算法单元测试

测试:
1. 数据导入验证逻辑
2. 单条指标计算（互动率、涨粉效率等）
3. 复盘分析（同类对比、归因分析）
4. 权重补丁生成（连续趋势检测）
"""

import sys
import os
import json
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from import_data import validate_entry, normalize_entry
from analyze_single import compute_metrics, grade_metric, find_peer_entries, attribute_performance
from generate_patches import check_consecutive, generate_weight_patches, group_by_content_line


# 加载测试用的样本数据
SAMPLE_DATA_PATH = os.path.join(os.path.dirname(__file__), 'sample_data', 'sample_platform_data.json')


def load_sample_entries():
    with open(SAMPLE_DATA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


class TestImportValidation(unittest.TestCase):
    """测试数据导入验证逻辑。"""

    def test_valid_entry_passes(self):
        """完整有效的条目应通过验证。"""
        entry = {
            "title": "测试视频",
            "date": "2026-03-01",
            "views": 100000,
            "completion_rate": 0.45,
            "likes": 2000,
            "comments": 300,
            "shares": 500
        }
        is_valid, errors = validate_entry(entry)
        self.assertTrue(is_valid, f"应通过验证，错误: {errors}")

    def test_missing_required_field_fails(self):
        """缺少必填字段应验证失败。"""
        entry = {"title": "测试视频"}  # 缺少date和views
        is_valid, errors = validate_entry(entry)
        self.assertFalse(is_valid)
        self.assertTrue(any("date" in e for e in errors))
        self.assertTrue(any("views" in e for e in errors))

    def test_invalid_completion_rate_fails(self):
        """完播率超出0-1范围应验证失败。"""
        entry = {
            "title": "测试视频",
            "date": "2026-03-01",
            "views": 100000,
            "completion_rate": 1.5  # 超过1
        }
        is_valid, errors = validate_entry(entry)
        self.assertFalse(is_valid)
        self.assertTrue(any("completion_rate" in e for e in errors))

    def test_invalid_date_format_fails(self):
        """错误的日期格式应验证失败。"""
        entry = {
            "title": "测试视频",
            "date": "2026/03/01",  # 错误格式
            "views": 100000
        }
        is_valid, errors = validate_entry(entry)
        self.assertFalse(is_valid)
        self.assertTrue(any("date" in e for e in errors))

    def test_normalize_converts_types(self):
        """标准化应将字符串数字转换为正确类型。"""
        entry = {
            "title": "测试",
            "date": "2026-03-01",
            "views": "100000",       # 字符串形式的数字
            "completion_rate": "0.42",  # 字符串形式的浮点数
            "likes": "2000"
        }
        normalized = normalize_entry(entry)
        self.assertIsInstance(normalized["views"], int)
        self.assertIsInstance(normalized["completion_rate"], float)
        self.assertIsInstance(normalized["likes"], int)


class TestComputeMetrics(unittest.TestCase):
    """测试单条内容指标计算。"""

    def setUp(self):
        self.entries = load_sample_entries()
        self.entry = self.entries[0]  # 315外泌体，460000播放

    def test_engagement_rate_calculated(self):
        """互动率 = (点赞+评论+分享) / 播放量。"""
        metrics = compute_metrics(self.entry)
        expected = (8500 + 1200 + 3400) / 460000
        self.assertAlmostEqual(metrics["engagement_rate"], expected, places=4)

    def test_share_rate_calculated(self):
        """分享率 = 分享 / 播放量。"""
        metrics = compute_metrics(self.entry)
        expected = 3400 / 460000
        self.assertAlmostEqual(metrics["share_rate"], expected, places=4)

    def test_follower_efficiency_calculated(self):
        """涨粉效率 = 新增粉丝 / 播放量 * 10000。"""
        metrics = compute_metrics(self.entry)
        expected = 850 / 460000 * 10000
        self.assertAlmostEqual(metrics["follower_efficiency"], expected, places=2)

    def test_zero_views_returns_zero_rates(self):
        """零播放量时，所有比率应为0而非除零错误。"""
        entry = {"views": 0, "likes": 100, "shares": 50}
        metrics = compute_metrics(entry)
        self.assertEqual(metrics["engagement_rate"], 0)
        self.assertEqual(metrics["share_rate"], 0)
        self.assertEqual(metrics["follower_efficiency"], 0)

    def test_grade_metric_excellent(self):
        """高于优秀基准时，应评为优秀。"""
        grade = grade_metric(0.06, "engagement_rate")  # 基准优秀为0.05
        self.assertIn("优秀", grade)

    def test_grade_metric_poor(self):
        """低于平均基准时，应评为较差。"""
        grade = grade_metric(0.005, "engagement_rate")  # 基准平均为0.01
        self.assertIn("较差", grade)

    def test_grade_metric_none_returns_missing(self):
        """None值应返回数据缺失。"""
        grade = grade_metric(None, "completion_rate")
        self.assertIn("数据缺失", grade)


class TestPeerComparison(unittest.TestCase):
    """测试同类内容对比逻辑。"""

    def setUp(self):
        self.entries = load_sample_entries()

    def test_finds_same_content_type_peers(self):
        """应找到同content_type的条目作为对比组。"""
        # 找一个"传播款"条目
        spread_entry = next(e for e in self.entries if e.get("content_type") == "传播款")
        peers = find_peer_entries(spread_entry, self.entries)
        # 对比组不应包含自身
        self.assertNotIn(spread_entry, peers)

    def test_peer_group_excludes_self(self):
        """对比组不应包含目标条目本身。"""
        entry = self.entries[0]
        peers = find_peer_entries(entry, self.entries)
        self.assertNotIn(entry, peers)

    def test_returns_all_entries_when_no_content_type(self):
        """无content_type时，回退使用全部条目对比。"""
        entry = {"title": "测试", "date": "2026-01-01", "views": 100}
        peers = find_peer_entries(entry, self.entries)
        self.assertEqual(len(peers), len(self.entries))


class TestAttributePerformance(unittest.TestCase):
    """测试表现归因分析。"""

    def setUp(self):
        self.entries = load_sample_entries()

    def test_number_in_title_detected(self):
        """标题含数字应被归因为正面因素。"""
        entry = {
            "title": "骨质疏松别乱补钙！医生不说的5个真相",
            "publish_time": "20:30",
            "content_type": "传播款",
            "views": 280000,
            "likes": 6100, "comments": 980, "shares": 2800,
            "followers_gained": 560, "completion_rate": 0.38
        }
        metrics = compute_metrics(entry)
        peer_avg = {"completion_rate": 0.4, "avg_views": 200000}
        attributions = attribute_performance(entry, metrics, peer_avg)
        # 标题含"5"，应该被归因
        has_number_attr = any("数字" in a for a in attributions)
        self.assertTrue(has_number_attr, f"应提到标题含数字的归因，得到: {attributions}")

    def test_golden_time_detected(self):
        """晚间黄金时段发布应被归因为正面因素。"""
        entry = {
            "title": "测试视频",
            "publish_time": "20:00",
            "content_type": "传播款",
            "views": 100000,
            "likes": 1000, "comments": 200, "shares": 300,
            "followers_gained": 100, "completion_rate": 0.4
        }
        metrics = compute_metrics(entry)
        attributions = attribute_performance(entry, metrics, {})
        has_time_attr = any("黄金" in a or "时段" in a for a in attributions)
        self.assertTrue(has_time_attr, f"应提到发布时间归因，得到: {attributions}")

    def test_low_completion_rate_flagged(self):
        """明显低于同类的完播率应被归因为问题。"""
        entry = {
            "title": "测试视频",
            "publish_time": "20:00",
            "content_type": None,
            "views": 100000,
            "likes": 1000, "comments": 200, "shares": 300,
            "followers_gained": 100, "completion_rate": 0.15  # 很低
        }
        metrics = compute_metrics(entry)
        peer_avg = {"completion_rate": 0.45}  # 同类均值
        attributions = attribute_performance(entry, metrics, peer_avg)
        has_low_cr_attr = any("完播率" in a and "低" in a for a in attributions)
        self.assertTrue(has_low_cr_attr, f"应标记完播率低，得到: {attributions}")


class TestCheckConsecutive(unittest.TestCase):
    """测试连续趋势检测算法。"""

    def test_detects_consecutive_above(self):
        """连续3个值超过阈值应返回True。"""
        values = [50000, 120000, 150000, 200000]
        result = check_consecutive(values, "above", 100000, 3)
        self.assertTrue(result)

    def test_not_consecutive_returns_false(self):
        """不连续的高值不应触发。"""
        values = [120000, 50000, 130000, 140000]
        result = check_consecutive(values, "above", 100000, 3)
        self.assertFalse(result)

    def test_below_threshold_detected(self):
        """连续2个值低于阈值应被检测到。"""
        values = [0.20, 0.22, 0.30]
        result = check_consecutive(values, "below", 0.25, 2)
        self.assertTrue(result)

    def test_none_values_break_streak(self):
        """None值应打断连续计数。"""
        values = [120000, None, 130000, 140000]
        # None打断，后面只有2个连续，不满足3个条件
        result = check_consecutive(values, "above", 100000, 3)
        self.assertFalse(result)

    def test_insufficient_data_returns_false(self):
        """数据量不足时不应误报。"""
        values = [120000]
        result = check_consecutive(values, "above", 100000, 3)
        self.assertFalse(result)


class TestGenerateWeightPatches(unittest.TestCase):
    """测试权重补丁生成。"""

    def setUp(self):
        self.entries = load_sample_entries()

    def test_patches_output_structure(self):
        """补丁输出应含delta和reason字段。"""
        groups = group_by_content_line(self.entries)
        patches = generate_weight_patches(groups, min_samples=2)
        for line, patch in patches.items():
            self.assertIn("delta", patch)
            self.assertIn("reason", patch)
            self.assertIn("sample_count", patch)

    def test_delta_within_reasonable_range(self):
        """Delta绝对值不应超过0.2（防止极端调整）。"""
        groups = group_by_content_line(self.entries)
        patches = generate_weight_patches(groups, min_samples=2)
        for patch in patches.values():
            self.assertLessEqual(abs(patch["delta"]), 0.20)

    def test_insufficient_samples_skipped(self):
        """样本不足的内容主线不应生成补丁。"""
        # 只给每组1条数据
        single_entries = [self.entries[0]]
        groups = group_by_content_line(single_entries)
        patches = generate_weight_patches(groups, min_samples=3)
        self.assertEqual(len(patches), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
