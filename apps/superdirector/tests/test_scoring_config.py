from __future__ import annotations

import json

from pipeline import scoring_config


def _seed_weights(tmp_path):
    for platform in scoring_config.PLATFORMS:
        (tmp_path / f"weights_{platform}.json").write_text(
            json.dumps(
                {
                    "emotion": 1.0,
                    "timely": 1.0,
                    "subvert": 1.0,
                    "relate": 1.0,
                    "spread": 1.0,
                    "tension": 1.0,
                    "depth": 1.0,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    (tmp_path / "source_weights.json").write_text(
        json.dumps(scoring_config.DEFAULT_SOURCE_WEIGHT_BY_BUCKET, ensure_ascii=False),
        encoding="utf-8",
    )


def test_scoring_snapshot_and_restore(monkeypatch, tmp_path):
    _seed_weights(tmp_path)
    monkeypatch.setattr(scoring_config, "WEIGHTS_DIR", tmp_path)
    monkeypatch.setattr(scoring_config, "SOURCE_WEIGHTS_PATH", tmp_path / "source_weights.json")
    monkeypatch.setattr(scoring_config, "SCORING_HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(scoring_config, "SCORING_PREVIEW_DIR", tmp_path / "previews")

    snapshot = scoring_config.create_scoring_snapshot(
        reason="test_apply",
        instruction="提高抖音传播权重",
        patch={"platform_weights": {"douyin": {"spread": 1.2}}},
        actor="pytest",
    )
    history = scoring_config.list_scoring_history(limit=5)

    assert history
    assert history[0]["snapshot_id"] == snapshot["snapshot_id"]

    scoring_config.save_platform_weights(
        "douyin",
        {
            "emotion": 1.0,
            "timely": 1.0,
            "subvert": 1.0,
            "relate": 1.0,
            "spread": 2.0,
            "tension": 1.0,
            "depth": 1.0,
        },
    )
    restored = scoring_config.restore_scoring_snapshot(snapshot["snapshot_id"])
    current = scoring_config.load_platform_weights("douyin")

    assert restored["snapshot_id"] == snapshot["snapshot_id"]
    assert current["spread"] == 1.0


def test_scoring_preview_roundtrip(monkeypatch, tmp_path):
    _seed_weights(tmp_path)
    monkeypatch.setattr(scoring_config, "WEIGHTS_DIR", tmp_path)
    monkeypatch.setattr(scoring_config, "SOURCE_WEIGHTS_PATH", tmp_path / "source_weights.json")
    monkeypatch.setattr(scoring_config, "SCORING_HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(scoring_config, "SCORING_PREVIEW_DIR", tmp_path / "previews")

    preview = scoring_config.create_scoring_preview(
        instruction="降低官方源加分",
        patch={"source_weights": {"official": 0.28}},
        usage={"provider": "qwen"},
    )
    loaded = scoring_config.load_scoring_preview(preview["preview_id"])

    assert loaded["preview_id"] == preview["preview_id"]
    assert loaded["patch"]["source_weights"]["official"] == 0.28
