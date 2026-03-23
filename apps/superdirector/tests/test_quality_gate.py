from types import SimpleNamespace

from pipeline.quality_gate import quality_gate


def topic(title: str, score: float, source: str):
    return SimpleNamespace(title=title, score_total=score, source=source)


def test_quality_gate_fails_when_raw_items_too_low():
    passed, reason = quality_gate([topic("标题", 4.0, "wechat_rss")], raw_item_count=4)
    assert passed is False
    assert "信源不足" in reason


def test_quality_gate_fails_when_top3_single_source():
    topics = [
        topic("题目1", 4.2, "brave_search"),
        topic("题目2", 4.1, "brave_search"),
        topic("题目3", 4.0, "brave_search"),
    ]
    passed, reason = quality_gate(topics, raw_item_count=8)
    assert passed is False
    assert "信源单一" in reason


def test_quality_gate_fails_on_english_titles():
    topics = [
        topic("Yang Sheng meets with US FDA Commissioner", 4.5, "nmpa_news"),
        topic("中文题目二", 4.2, "wechat_rss"),
        topic("中文题目三", 4.0, "baidu_search"),
    ]
    passed, reason = quality_gate(topics, raw_item_count=8)
    assert passed is False
    assert "英文标题" in reason


def test_quality_gate_passes_on_diverse_top3():
    topics = [
        topic("题目1", 4.5, "wechat_rss"),
        topic("题目2", 4.2, "brave_search"),
        topic("题目3", 4.0, "baidu_search"),
    ]
    passed, reason = quality_gate(topics, raw_item_count=8)
    assert passed is True
    assert reason == "通过"


def test_quality_gate_uses_editorial_presentation_order_instead_of_resorting_by_score():
    topics = [
        {
            "title": "家庭自查药盒三步走",
            "score_total": 4.0,
            "source": "wechat_rss",
            "topic_line_primary": "family_anxiety",
            "content_role": "save",
            "topic_cluster": "家庭药箱",
        },
        {
            "title": "315点名外泌体",
            "score_total": 4.8,
            "source": "wechat_rss",
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "抗衰骗局",
        },
        {
            "title": "进了医保，为什么医院还是开不出来？",
            "score_total": 4.6,
            "source": "baidu_search",
            "topic_line_primary": "public_issue",
            "content_role": "save",
            "topic_cluster": "医保进院难",
        },
    ]

    passed, reason = quality_gate(topics, raw_item_count=8)

    assert passed is True
    assert reason == "通过"
