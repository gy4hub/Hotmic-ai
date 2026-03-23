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
