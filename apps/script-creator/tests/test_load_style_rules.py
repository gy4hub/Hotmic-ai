#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from load_style_rules import format_profile_summary, load_creator_profile


def test_load_creator_profile_reads_explicit_profile(tmp_path):
    profile_path = tmp_path / "casey_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "account_id": "casey",
                "display_name": "添爸",
                "positioning": {"one_liner": "测试定位"},
                "dual_audience_model": {
                    "decision_layer": {"label": "李姐", "who": "决策受众"},
                    "spread_layer": {"label": "张阿姨", "who": "传播受众"},
                },
                "content_mix": {
                    "lines": [
                        {"key": "public_issue", "name": "医疗公共议题", "weight": 0.5}
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    profile = load_creator_profile(profile_path=str(profile_path))

    assert profile["account_id"] == "casey"
    assert profile["display_name"] == "添爸"


def test_format_profile_summary_includes_audience_and_mix():
    summary = format_profile_summary(
        {
            "account_id": "casey",
            "display_name": "添爸",
            "positioning": {"one_liner": "测试定位"},
            "dual_audience_model": {
                "decision_layer": {"label": "李姐", "who": "决策受众"},
                "spread_layer": {"label": "张阿姨", "who": "传播受众"},
            },
            "content_mix": {
                "lines": [
                    {"key": "public_issue", "name": "医疗公共议题", "weight": 0.5}
                ]
            },
        }
    )

    assert "测试定位" in summary
    assert "决策层: 李姐 | 决策受众" in summary
    assert "传播层: 张阿姨 | 传播受众" in summary
    assert "医疗公共议题: 0.5" in summary
