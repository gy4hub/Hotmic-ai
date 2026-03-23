import asyncio
import importlib
import httpx


def test_analyzer_mock(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")
    import config
    import pipeline.analyzer as analyzer

    importlib.reload(config)
    importlib.reload(analyzer)

    topics = [{"title": "t", "url": "u", "source": "s", "timestamp": "", "raw_snippet": ""}]
    results, errors, _ = asyncio.run(analyzer.analyze_topics(None, None, topics))
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert errors == []


def test_build_results_realigns_reordered_items():
    import pipeline.analyzer as analyzer

    topics = [
        {"title": "两家医院，合并了", "url": "u1"},
        {"title": "一个医保报销“bug”，卡住了PD-1", "url": "u2"},
    ]
    parsed_items = [
        {
            "input_index": 1,
            "input_title": "一个医保报销“bug”，卡住了PD-1",
            "summary": "PD-1 报销 bug",
            "keywords": ["PD-1"],
            "angle_type": "A",
            "content_type": "policy",
            "competitor_angle": "x",
            "angle_gap": "y",
            "scores": {"emotion": 5},
        },
        {
            "input_index": 0,
            "input_title": "两家医院，合并了",
            "summary": "医院合并",
            "keywords": ["医院"],
            "angle_type": "C",
            "content_type": "trend",
            "competitor_angle": "x",
            "angle_gap": "y",
            "scores": {"emotion": 3},
        },
    ]

    results = analyzer._build_results(topics, parsed_items)

    assert results[0]["title"] == "两家医院，合并了"
    assert results[0]["summary"] == "医院合并"
    assert results[1]["title"] == "进了医保，为什么医院还是开不出来？"
    assert results[1]["summary"] == "PD-1 报销 bug"


def test_build_results_localizes_english_title_when_available():
    import pipeline.analyzer as analyzer

    topics = [{"title": "9 December 2025 Medical product alert", "url": "u1"}]
    parsed_items = [
        {
            "input_index": 0,
            "input_title": "9 December 2025 Medical product alert",
            "localized_title": "WHO通报假药警报：移植针剂出事了",
            "summary": "假药警报",
            "keywords": ["假药"],
            "angle_type": "B",
            "content_type": "event",
            "competitor_angle": "x",
            "angle_gap": "y",
            "scores": {"emotion": 5},
        }
    ]

    results = analyzer._build_results(topics, parsed_items)

    assert results[0]["title"] == "WHO通报假药警报：移植针剂出事了"


def test_build_results_uses_localized_title_for_bug_style_or_promo_titles():
    import pipeline.analyzer as analyzer

    topics = [
        {"title": "一个医保报销“bug”，卡住了PD-1", "url": "u1"},
        {"title": "315曝光的外泌体，彻底火了！我们诚邀您一起探讨外泌体行业的未来发展！", "url": "u2"},
    ]
    parsed_items = [
        {
            "input_index": 0,
            "input_title": "一个医保报销“bug”，卡住了PD-1",
            "localized_title": "进了医保，为什么医院还是开不出来？",
            "summary": "医保进院难",
            "keywords": ["医保", "开不出来"],
            "angle_type": "A",
            "content_type": "policy",
            "competitor_angle": "x",
            "angle_gap": "y",
            "scores": {"emotion": 5},
        },
        {
            "input_index": 1,
            "input_title": "315曝光的外泌体，彻底火了！我们诚邀您一起探讨外泌体行业的未来发展！",
            "localized_title": "315点名外泌体：没有批文，为何还敢卖3针6万？",
            "summary": "外泌体315",
            "keywords": ["315", "外泌体"],
            "angle_type": "B",
            "content_type": "event",
            "competitor_angle": "x",
            "angle_gap": "y",
            "scores": {"emotion": 5},
        },
    ]

    results = analyzer._build_results(topics, parsed_items)

    assert results[0]["title"] == "进了医保，为什么医院还是开不出来？"
    assert results[1]["title"] == "315点名外泌体：听起来像高科技，为什么反而最该警惕？"


def test_build_results_applies_house_style_rewrite_without_model_localized_title():
    import pipeline.analyzer as analyzer

    topics = [
        {"title": "一个医保报销“bug”，卡住了PD-1", "url": "u1"},
        {"title": "315刚点名的‘外泌体’，现在又在开大会？", "url": "u2"},
    ]
    parsed_items = [
        {
            "input_index": 0,
            "input_title": "一个医保报销“bug”，卡住了PD-1",
            "summary": "药进医保了，患者还是用不上。",
            "keywords": ["医保", "开不出来", "PD-1"],
            "scores": {"emotion": 5},
        },
        {
            "input_index": 1,
            "input_title": "315刚点名的‘外泌体’，现在又在开大会？",
            "summary": "315后仍在借高科技话术卖高价项目。",
            "keywords": ["315", "外泌体"],
            "scores": {"emotion": 5},
        },
    ]

    results = analyzer._build_results(topics, parsed_items)

    assert results[0]["title"] == "进了医保，为什么医院还是开不出来？"
    assert results[1]["title"] == "315点名外泌体：听起来像高科技，为什么反而最该警惕？"


def test_describe_exception_handles_blank_messages():
    import pipeline.analyzer as analyzer

    exc = httpx.ReadTimeout("")
    text = analyzer._describe_exception(exc)

    assert "ReadTimeout" in text


def test_chunk_topics_respects_batch_size():
    import pipeline.analyzer as analyzer

    batches = list(analyzer._chunk_topics([1, 2, 3, 4, 5], 2))

    assert batches == [[1, 2], [3, 4], [5]]


def test_analysis_input_topic_trims_payload():
    import pipeline.analyzer as analyzer

    prepared = analyzer._analysis_input_topic(
        {
            "_analysis_index": 1,
            "title": "a" * 300,
            "url": "u",
            "source": "s",
            "timestamp": "t",
            "raw_snippet": "b" * 400,
            "fingerprint": "ignore-me",
        }
    )

    assert len(prepared["title"]) == 160
    assert len(prepared["raw_snippet"]) == 280
    assert "fingerprint" not in prepared
