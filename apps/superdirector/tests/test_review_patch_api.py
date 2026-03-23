from __future__ import annotations

import asyncio
import json
from pathlib import Path

import config as app_config
from pipeline import editorial
from pipeline import review_patch
from tools import api_routes


class DummyRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def _write_profile(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "account_id": "casey",
                "content_mix": {
                    "lines": [
                        {"key": "public_issue", "name": "医疗公共议题", "weight": 0.5},
                        {"key": "family_anxiety", "name": "家庭健康焦虑", "weight": 0.3},
                        {"key": "consumer_scam", "name": "健康消费避坑", "weight": 0.2},
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_style_db(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "last_updated": "",
                "statistics": {
                    "total_diffs_analyzed": 0,
                    "avg_edit_ratio": 0.0,
                    "edit_ratio_history": [],
                },
                "rules": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_apply_sd_weight_patch_rebalances_profile_and_runtime(monkeypatch, tmp_path):
    profile_path = tmp_path / "casey_profile.json"
    _write_profile(profile_path)

    monkeypatch.setattr(
        app_config,
        "EDITORIAL_TARGET_MIX_DEFAULT",
        {"public_issue": 0.5, "family_anxiety": 0.3, "consumer_scam": 0.2},
    )
    monkeypatch.setattr(
        editorial,
        "EDITORIAL_TARGET_MIX_DEFAULT",
        {"public_issue": 0.5, "family_anxiety": 0.3, "consumer_scam": 0.2},
    )

    result = review_patch.apply_sd_weight_patch(
        {"医疗公共议题": {"delta": 0.05, "reason": "连续3条播放量>10万"}},
        profile_path=profile_path,
    )

    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    saved_weights = {item["key"]: item["weight"] for item in saved["content_mix"]["lines"]}

    assert result["applied"]["public_issue"]["delta"] == 0.05
    assert round(sum(saved_weights.values()), 6) == 1.0
    assert saved_weights["public_issue"] == 0.55
    assert saved_weights["family_anxiety"] == 0.27
    assert saved_weights["consumer_scam"] == 0.18
    assert app_config.EDITORIAL_TARGET_MIX_DEFAULT["public_issue"] == 0.55
    assert editorial.EDITORIAL_TARGET_MIX_DEFAULT["consumer_scam"] == 0.18


def test_apply_style_patch_writes_review_rule_to_style_db(tmp_path):
    style_db_path = tmp_path / "style_db.json"
    _write_style_db(style_db_path)

    result = review_patch.apply_style_patch(
        [
            {
                "rule": "标题含具体数字的3条视频均播放量更高",
                "confidence": 0.72,
                "action": "建议在标题中加入具体数字（如315、3种方法、5个误区）",
            }
        ],
        style_db_path=style_db_path,
    )

    saved = json.loads(style_db_path.read_text(encoding="utf-8"))
    saved_rule = saved["rules"][0]

    assert result["created"] == 1
    assert saved_rule["rule"] == "建议在标题中加入具体数字（如315、3种方法、5个误区）"
    assert saved_rule["confidence"] == 0.72
    assert saved_rule["evidence"] == "标题含具体数字的3条视频均播放量更高"


def test_scoring_apply_review_patch_endpoint_creates_snapshot(monkeypatch, tmp_path):
    profile_path = tmp_path / "casey_profile.json"
    style_db_path = tmp_path / "style_db.json"
    _write_profile(profile_path)
    _write_style_db(style_db_path)

    snapshots = []

    def fake_create_scoring_snapshot(*, reason, instruction=None, patch=None, actor="system"):
        snapshots.append(
            {
                "reason": reason,
                "instruction": instruction,
                "patch": patch,
                "actor": actor,
            }
        )
        return {"snapshot_id": "snap-1", "reason": reason}

    monkeypatch.setattr(api_routes, "create_scoring_snapshot", fake_create_scoring_snapshot)
    monkeypatch.setattr(
        api_routes,
        "apply_review_patch",
        lambda payload: review_patch.apply_review_patch(
            payload,
            profile_path=profile_path,
            style_db_path=style_db_path,
        ),
    )

    result = asyncio.run(
        api_routes.scoring_apply_review_patch(
            DummyRequest(
                {
                    "sd_weight_patch": {
                        "家庭健康焦虑": {"delta": -0.05, "reason": "近3条完播偏低"}
                    },
                    "style_patch": [
                        {
                            "rule": "短视频完播率更高",
                            "confidence": 0.8,
                            "action": "建议默认控制视频时长在3分钟以内",
                        }
                    ],
                }
            )
        )
    )

    assert result["applied"] is True
    assert result["snapshot"]["snapshot_id"] == "snap-1"
    assert snapshots[0]["reason"] == "apply_review_patch"
    assert "family_anxiety" in result["apply_result"]["sd_weight_patch"]["applied"]
    assert result["apply_result"]["style_patch"]["created"] == 1
