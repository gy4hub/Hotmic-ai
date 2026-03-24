from pipeline.scorer import score_topics


def test_score_topics_basic():
    analyzed = [
        {
            "topic_id": "t1",
            "source": "wechat_rss",
            "scores": {
                "emotion": 5,
                "timely": 4,
                "subvert": 3,
                "relate": 4,
                "spread": 3,
                "tension": 2,
                "depth": 4,
            },
        }
    ]
    scored, details = score_topics(analyzed)
    assert scored[0]["score_total"] > 0
    assert len(details) > 0
    assert scored[0]["source_tier"] == "trusted_rss"


def test_source_bonus_prefers_official_over_search():
    analyzed = [
        {
            "topic_id": "official",
            "source": "who_alerts",
            "scores": {
                "emotion": 4,
                "timely": 4,
                "subvert": 4,
                "relate": 4,
                "spread": 4,
                "tension": 4,
                "depth": 4,
            },
        },
        {
            "topic_id": "search",
            "source": "brave_biotech_cn",
            "scores": {
                "emotion": 4,
                "timely": 4,
                "subvert": 4,
                "relate": 4,
                "spread": 4,
                "tension": 4,
                "depth": 4,
            },
        },
    ]
    scored, _details = score_topics(analyzed)
    assert scored[0]["topic_id"] == "official"
    assert scored[0]["source_tier"] == "official"


def test_cluster_mismatch_applies_penalty():
    analyzed = [
        {
            "topic_id": "aligned",
            "source": "wechat_rss",
            "cluster_mismatch": False,
            "scores": {
                "emotion": 4,
                "timely": 4,
                "subvert": 4,
                "relate": 4,
                "spread": 4,
                "tension": 4,
                "depth": 4,
            },
        },
        {
            "topic_id": "mismatch",
            "source": "wechat_rss",
            "cluster_mismatch": True,
            "scores": {
                "emotion": 4,
                "timely": 4,
                "subvert": 4,
                "relate": 4,
                "spread": 4,
                "tension": 4,
                "depth": 4,
            },
        },
    ]

    scored, _details = score_topics(analyzed)
    aligned = next(item for item in scored if item["topic_id"] == "aligned")
    mismatch = next(item for item in scored if item["topic_id"] == "mismatch")

    assert mismatch["cluster_mismatch"] is True
    assert mismatch["score_total"] == round(aligned["score_total"] * 0.85, 4)
    assert mismatch["cluster_mismatch_penalty"] == round(aligned["score_total"] - mismatch["score_total"], 4)


def test_new_source_buckets_are_scored_explicitly():
    analyzed = [
        {
            "topic_id": "evergreen",
            "source": "evergreen",
            "scores": {
                "emotion": 4,
                "timely": 3,
                "subvert": 4,
                "relate": 4,
                "spread": 4,
                "tension": 3,
                "depth": 5,
            },
        },
        {
            "topic_id": "industry",
            "source": "wx_saibolan",
            "scores": {
                "emotion": 4,
                "timely": 3,
                "subvert": 4,
                "relate": 4,
                "spread": 4,
                "tension": 3,
                "depth": 5,
            },
        },
        {
            "topic_id": "competitor",
            "source": "competitor_老蒋巨靠谱",
            "scores": {
                "emotion": 4,
                "timely": 3,
                "subvert": 4,
                "relate": 4,
                "spread": 4,
                "tension": 3,
                "depth": 5,
            },
        },
    ]

    scored, _details = score_topics(analyzed)
    by_id = {item["topic_id"]: item for item in scored}

    assert by_id["evergreen"]["source_tier"] == "trusted_rss"
    assert by_id["industry"]["source_tier"] == "industry_media"
    assert by_id["competitor"]["source_tier"] == "search"
