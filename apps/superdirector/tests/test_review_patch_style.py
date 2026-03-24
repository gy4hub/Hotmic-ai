from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pipeline import review_patch


def test_apply_style_patch_dedupes_and_filters_low_confidence(monkeypatch, tmp_path):
    saved_db: dict = {}

    def load_style_db(_path: str):
        return {
            "rules": [
                {
                    "id": "rule-1",
                    "category": "hook",
                    "rule": "先给结论再解释",
                    "confidence": 0.7,
                    "last_validated": "2026-03-01",
                }
            ]
        }

    def find_matching_rule(candidate: dict, rules: list[dict]):
        for rule in rules:
            if rule.get("rule") == candidate.get("rule"):
                return rule
        return None

    def save_style_db(db: dict, _path: str):
        saved_db.clear()
        saved_db.update(db)

    fake_module = SimpleNamespace(
        load_style_db=load_style_db,
        find_matching_rule=find_matching_rule,
        save_style_db=save_style_db,
        generate_rule_id=lambda rules: f"rule-{len(rules) + 1}",
        datetime=SimpleNamespace(now=lambda: SimpleNamespace(strftime=lambda _fmt: "2026-03-24")),
    )
    monkeypatch.setattr(review_patch, "_hotmic_update_style_module", lambda: fake_module)
    monkeypatch.setattr(review_patch, "HOTMIC_STYLE_CONFIDENCE_THRESHOLD", 0.6)

    result = review_patch.apply_style_patch(
        [
            {
                "category": "hook",
                "action": "先给结论再解释",
                "rule": "保留结论前置",
                "confidence": 0.9,
                "last_validated": "2026-03-24",
            },
            {
                "category": "cta",
                "action": "结尾给一个明确行动建议",
                "confidence": 0.58,
            },
            {
                "category": "cta",
                "action": "结尾保留一句提醒",
                "confidence": 0.82,
                "status": "active",
            },
        ],
        style_db_path=Path(tmp_path) / "style_db.json",
    )

    assert result["updated"] == 1
    assert result["created"] == 1
    assert result["skipped"] == 1
    assert len(saved_db["rules"]) == 2
    assert saved_db["rules"][0]["confidence"] == 0.9
    assert saved_db["rules"][1]["rule"] == "结尾保留一句提醒"
