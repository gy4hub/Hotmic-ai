import json

from pipeline import scorer, scoring_config, scoring_tuner


def test_explain_scores_reports_selected_platform():
    explanation = scorer.explain_scores(
        {
            "emotion": 5,
            "timely": 4,
            "subvert": 3,
            "relate": 4,
            "spread": 5,
            "tension": 2,
            "depth": 3,
        },
        "wechat_rss",
    )

    assert explanation["selected_platform"] in {"douyin", "xiaohongshu", "shipinhao"}
    assert explanation["final_score"] >= explanation["base_score"]
    assert explanation["source_tier"] == "trusted_rss"


def test_apply_scoring_patch_writes_updated_files(monkeypatch, tmp_path):
    weights_dir = tmp_path / "config"
    weights_dir.mkdir()
    for platform in scorer.PLATFORMS:
        (weights_dir / f"weights_{platform}.json").write_text(
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
    source_weights_path = weights_dir / "source_weights.json"
    source_weights_path.write_text(
        json.dumps(scorer.DEFAULT_SOURCE_WEIGHT_BY_BUCKET, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(scoring_config, "WEIGHTS_DIR", weights_dir)
    monkeypatch.setattr(scoring_config, "SOURCE_WEIGHTS_PATH", source_weights_path)
    monkeypatch.setattr(scoring_tuner, "WEIGHTS_DIR", weights_dir)
    monkeypatch.setattr(scoring_tuner, "SOURCE_WEIGHTS_PATH", source_weights_path)

    result = scoring_tuner.apply_scoring_patch(
        {
            "summary": "提高抖音传播，降低搜索源加分",
            "platform_weights": {"douyin": {"spread": 1.6}},
            "source_weights": {"search": 0.0},
            "notes": [],
        }
    )

    updated_douyin = json.loads((weights_dir / "weights_douyin.json").read_text(encoding="utf-8"))
    updated_sources = json.loads(source_weights_path.read_text(encoding="utf-8"))

    assert updated_douyin["spread"] == 1.6
    assert updated_sources["search"] == 0.0
    assert result["changed_platforms"]["douyin"]["spread"] == 1.6
