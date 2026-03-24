import asyncio
import importlib
import httpx
from types import SimpleNamespace


class DummyResponse:
    def __init__(self, *, json_data=None, status_code=200):
        self._json_data = json_data or {}
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


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
    assert results[1]["title"] == "一个医保报销“bug”，卡住了PD-1"
    assert results[1]["original_title"] == "一个医保报销“bug”，卡住了PD-1"
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
    assert results[0]["localized_title"] == "WHO通报假药警报：移植针剂出事了"
    assert results[0]["original_title"] == "9 December 2025 Medical product alert"


def test_build_results_keeps_model_localized_title_without_house_style_rewrite():
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
    assert results[0]["original_title"] == "一个医保报销“bug”，卡住了PD-1"
    assert results[1]["title"] == "315点名外泌体：没有批文，为何还敢卖3针6万？"
    assert results[1]["localized_title"] == "315点名外泌体：没有批文，为何还敢卖3针6万？"


def test_build_results_preserves_original_title_without_model_localized_title():
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

    assert results[0]["title"] == "一个医保报销“bug”，卡住了PD-1"
    assert results[0]["original_title"] == "一个医保报销“bug”，卡住了PD-1"
    assert results[1]["title"] == "315刚点名的‘外泌体’，现在又在开大会？"
    assert results[1]["localized_title"] == ""


def test_rewrite_title_for_house_style_removed():
    import pipeline.analyzer as analyzer

    assert not hasattr(analyzer, "_rewrite_title_for_house_style")


def test_source_cluster_consistency_marks_expected_mismatches():
    import pipeline.analyzer as analyzer

    mismatch_cases = [
        {
            "url": "https://www.nytimes.com/2026/03/24/health/ozempic-supply.html",
            "source": "rss_nyt_health",
            "original_title": "Ozempic demand rises",
            "topic_cluster": "医保进院难",
        },
        {
            "url": "https://www.gov.cn/zhengce/2026-03/24/content_123.htm",
            "source": "govcn_policy",
            "original_title": "医保政策调整",
            "topic_cluster": "司美格鲁肽灰市",
        },
        {
            "url": "https://www.36kr.com/p/123456789",
            "source": "rss_36kr",
            "original_title": "外泌体创业火了",
            "topic_cluster": "药品安全警报",
        },
    ]
    matched_cases = [
        {
            "url": "https://www.nytimes.com/2026/03/24/health/ozempic-supply.html",
            "source": "rss_nyt_health",
            "original_title": "Ozempic demand rises",
            "topic_cluster": "司美格鲁肽灰市",
        },
        {
            "url": "https://www.gov.cn/zhengce/2026-03/24/content_123.htm",
            "source": "govcn_policy",
            "original_title": "医保进院难问题调查",
            "topic_cluster": "医保进院难",
        },
        {
            "url": "https://www.fda.gov/safety/medwatch-safety-alert",
            "source": "fda_safety",
            "original_title": "Safety alert",
            "topic_cluster": "药品安全警报",
        },
    ]

    for case in mismatch_cases:
        assert analyzer._check_source_cluster_consistency(case) is True
    for case in matched_cases:
        assert analyzer._check_source_cluster_consistency(case) is False


def test_prefilter_topics_filters_irrelevant_entries(monkeypatch):
    import pipeline.analyzer as analyzer

    async def fake_request_with_retry(_client, _method, url, **kwargs):
        assert url.endswith("/chat/completions")
        return DummyResponse(
            json_data={
                "choices": [
                    {
                        "message": {
                            "content": '{"items": ['
                            '{"input_index": 0, "input_title": "NYT Ozempic outlook", "relevant": false, "score": 0.2, "reason": "美国商业新闻"},'
                            '{"input_index": 1, "input_title": "央视调查：医保进院难", "relevant": true, "score": 0.86, "reason": "医保政策强相关"}'
                            ']}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            }
        )

    monkeypatch.setattr(analyzer, "PREFILTER_ENABLED", True)
    monkeypatch.setattr(analyzer, "PREFILTER_MODEL", "qwen-plus")
    monkeypatch.setattr(analyzer, "PREFILTER_THRESHOLD", 0.3)
    monkeypatch.setattr(analyzer, "QWEN_API_KEY", "token")
    monkeypatch.setattr(analyzer, "request_with_retry", fake_request_with_retry)

    topics = [
        {"title": "NYT Ozempic outlook", "url": "https://nytimes.com/1", "source": "rss_nyt_health", "raw_snippet": "US market"},
        {"title": "央视调查：医保进院难", "url": "https://cctv.com/1", "source": "cctv", "raw_snippet": "医保政策"},
    ]

    filtered, errors, usage = asyncio.run(analyzer.prefilter_topics(object(), topics))

    assert errors == []
    assert [topic["title"] for topic in filtered] == ["央视调查：医保进院难"]
    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] == 6


def test_prefilter_topics_gracefully_falls_back_on_failure(monkeypatch):
    import pipeline.analyzer as analyzer

    async def fake_request_with_retry(*args, **kwargs):
        raise RuntimeError("prefilter boom")

    monkeypatch.setattr(analyzer, "PREFILTER_ENABLED", True)
    monkeypatch.setattr(analyzer, "PREFILTER_MODEL", "qwen-plus")
    monkeypatch.setattr(analyzer, "QWEN_API_KEY", "token")
    monkeypatch.setattr(analyzer, "request_with_retry", fake_request_with_retry)

    topics = [{"title": "医保新规", "url": "u1", "source": "govcn_policy"}]
    filtered, errors, usage = asyncio.run(analyzer.prefilter_topics(object(), topics))

    assert filtered == topics
    assert usage == {}
    assert "Prefilter failed: prefilter boom" in errors[0]


def test_resolve_compatible_llm_target_switches_between_qwen_deepseek_and_generic(monkeypatch):
    import pipeline.analyzer as analyzer

    monkeypatch.setattr(analyzer, "QWEN_API_KEY", "qwen-token")
    monkeypatch.setattr(analyzer, "QWEN_BASE_URL", "https://dashscope.example/v1")
    monkeypatch.setattr(analyzer, "DEEPSEEK_API_KEY", "deepseek-token")
    monkeypatch.setattr(analyzer, "DEEPSEEK_BASE_URL", "https://deepseek.example/v1")
    monkeypatch.setattr(analyzer, "ANALYZE_API_KEY", "generic-token")
    monkeypatch.setattr(analyzer, "ANALYZE_BASE_URL", "https://generic.example/v1")

    qwen_target = analyzer._resolve_compatible_llm_target("qwen-max")
    deepseek_target = analyzer._resolve_compatible_llm_target("deepseek-chat")
    generic_target = analyzer._resolve_compatible_llm_target("gpt-4o-mini")

    assert qwen_target == {
        "provider": "qwen",
        "model": "qwen-max",
        "base_url": "https://dashscope.example/v1",
        "api_key": "qwen-token",
    }
    assert deepseek_target == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://deepseek.example/v1",
        "api_key": "deepseek-token",
    }
    assert generic_target == {
        "provider": "openai-compatible",
        "model": "gpt-4o-mini",
        "base_url": "https://generic.example/v1",
        "api_key": "generic-token",
    }


def test_analyze_topics_uses_configured_analyze_model(monkeypatch):
    import pipeline.analyzer as analyzer

    captured: dict[str, str] = {}

    async def fake_request_with_retry(_client, _method, url, **kwargs):
        captured["url"] = url
        captured["auth"] = kwargs["headers"]["Authorization"]
        payload = kwargs["content"].decode("utf-8")
        captured["payload"] = payload
        return DummyResponse(
            json_data={
                "choices": [
                    {
                        "message": {
                            "content": '{"items": [{"input_index": 0, "input_title": "医保新规", "localized_title": "医保新规", "summary": "summary", "keywords": ["医保"], "scores": {"emotion": 4}}]}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )

    monkeypatch.setattr(analyzer, "QWEN_API_KEY", "")
    monkeypatch.setattr(analyzer, "ANALYZE_MODEL", "deepseek-chat")
    monkeypatch.setattr(analyzer, "DEEPSEEK_API_KEY", "deepseek-token")
    monkeypatch.setattr(analyzer, "DEEPSEEK_BASE_URL", "https://deepseek.example/v1")
    monkeypatch.setattr(analyzer, "request_with_retry", fake_request_with_retry)
    monkeypatch.setattr(analyzer, "build_editorial_prompt_section", lambda: "")

    results, errors, usage = asyncio.run(
        analyzer.analyze_topics(
            ext_client=object(),
            int_client=object(),
            topics=[{"title": "医保新规", "url": "u1", "source": "govcn_policy", "timestamp": "", "raw_snippet": ""}],
        )
    )

    assert errors == []
    assert results[0]["title"] == "医保新规"
    assert captured["url"] == "https://deepseek.example/v1/chat/completions"
    assert captured["auth"] == "Bearer deepseek-token"
    assert '"model": "deepseek-chat"' in captured["payload"]
    assert usage["provider"] == "deepseek"


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


def test_analysis_input_topic_infers_source_type():
    import pipeline.analyzer as analyzer

    evergreen = analyzer._analysis_input_topic(
        {
            "_analysis_index": 1,
            "title": "医保报销怎么看",
            "url": "hotmic://evergreen/eg_1",
            "source": "evergreen",
            "timestamp": "",
            "raw_snippet": "摘要",
        }
    )
    competitor = analyzer._analysis_input_topic(
        {
            "_analysis_index": 2,
            "title": "对标标题",
            "url": "https://douyin.com/1",
            "source": "competitor_老蒋巨靠谱",
            "timestamp": "",
            "raw_snippet": "摘要",
        }
    )

    assert evergreen["source_type"] == "evergreen"
    assert competitor["source_type"] == "competitor"


def test_analyze_topics_batches_in_two_calls_when_batch_size_is_eight(monkeypatch):
    import pipeline.analyzer as analyzer

    batch_sizes = []

    async def fake_analyze_with_llm(_int_client, topics):
        batch_sizes.append(len(topics))
        return (
            [
                {
                    **topic,
                    "topic_id": f"cached-{topic['_analysis_index']}",
                    "summary": "summary",
                    "keywords": ["医保"],
                    "scores": {"emotion": 3, "timely": 3, "subvert": 3, "relate": 3, "spread": 3, "tension": 3, "depth": 3},
                    "status": "ok",
                    "errors": [],
                }
                for topic in topics
            ],
            [],
            {},
        )

    monkeypatch.setattr(analyzer, "QWEN_API_KEY", "token")
    monkeypatch.setattr(analyzer, "ANALYZE_MODEL", "qwen-plus")
    monkeypatch.setattr(analyzer, "ANALYZER_BATCH_SIZE", 8)
    monkeypatch.setattr(analyzer, "ANALYZER_BATCH_CONCURRENCY", 1)
    monkeypatch.setattr(analyzer, "ANALYSIS_CACHE_ENABLED", False)
    monkeypatch.setattr(analyzer, "_analyze_with_llm", fake_analyze_with_llm)

    topics = [{"title": f"题目{i}", "url": f"https://example.com/{i}", "source": "wechat_rss"} for i in range(10)]
    results, errors, _usage = asyncio.run(analyzer.analyze_topics(object(), object(), topics))

    assert errors == []
    assert len(results) == 10
    assert batch_sizes == [8, 2]


def test_analyze_topics_reuses_cached_cluster_analysis(monkeypatch):
    import pipeline.analyzer as analyzer

    recent_row = SimpleNamespace(
        title="医保报销怎么看懂",
        original_title="医保报销怎么看懂",
        localized_title="医保报销怎么看懂",
        summary="缓存摘要",
        keywords='["医保","报销"]',
        angle_type="A",
        content_type="policy",
        competitor_angle="常见只讲结果",
        angle_gap="补制度逻辑",
        topic_line_primary="public_issue",
        topic_line_secondary=None,
        line_confidence=0.9,
        content_role="save",
        creator_fit="strong",
        li_jie_value="save",
        zhang_auntie_value="forward",
        audience_core="family_decision_maker",
        compliance_risk="low",
        actionability_risk="low",
        topic_cluster="医保报销",
        parent_topic_cluster=None,
        series_anchor_id=None,
        reject_type="none",
        rejection_reason=None,
        platform_fit="both",
        decision_impact_level="high",
        score_emotion=1,
        score_timely=1,
        score_subvert=4,
        score_relate=4,
        score_spread=4,
        score_tension=4,
        score_depth=4,
    )
    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_get_recent_editorial_topics(_session, *, since_days, limit):
        return [recent_row]

    async def fake_get_recent_cluster_analysis(_session, cluster, *, days):
        raise AssertionError("matched row should be reused directly")

    async def fake_analyze_with_llm(_int_client, topics):
        raise AssertionError("cache hit should bypass llm")

    monkeypatch.setattr(analyzer, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(analyzer.crud, "get_recent_editorial_topics", fake_get_recent_editorial_topics)
    monkeypatch.setattr(analyzer.crud, "get_recent_cluster_analysis", fake_get_recent_cluster_analysis)
    monkeypatch.setattr(analyzer, "ANALYSIS_CACHE_ENABLED", True)
    monkeypatch.setattr(analyzer, "ANALYSIS_CACHE_LOOKBACK_DAYS", 7)
    monkeypatch.setattr(analyzer, "ANALYZE_MODEL", "qwen-plus")
    monkeypatch.setattr(analyzer, "_analyze_with_llm", fake_analyze_with_llm)

    results, errors, usage = asyncio.run(
        analyzer.analyze_topics(
            object(),
            object(),
            [{"title": "医保报销怎么看懂", "url": "https://example.com/1", "source": "wechat_rss", "raw_snippet": "最新政策变化"}],
        )
    )

    assert errors == []
    assert usage == {}
    assert results[0]["topic_cluster"] == "医保报销"
    assert results[0]["scores"]["emotion"] >= 2
    assert results[0]["scores"]["timely"] >= 3


def test_analyze_with_gemini_returns_structured_results(monkeypatch):
    import pipeline.analyzer as analyzer

    async def fake_validate(_client):
        return True, None, False

    async def fake_request_with_retry(_client, _method, url, **kwargs):
        assert ":generateContent" in url
        return DummyResponse(
            json_data={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"items":[{"input_index":0,"input_title":"医保新规","localized_title":"医保新规","summary":"summary","keywords":["医保"],"scores":{"emotion":4,"timely":4,"subvert":3,"relate":4,"spread":3,"tension":3,"depth":4}}]}'
                                }
                            ]
                        }
                    }
                ],
                "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 4},
            }
        )

    monkeypatch.setattr(analyzer, "_validate_model", fake_validate)
    monkeypatch.setattr(analyzer, "request_with_retry", fake_request_with_retry)
    monkeypatch.setattr(analyzer, "build_editorial_prompt_section", lambda: "")
    monkeypatch.setattr(analyzer, "GEMINI_API_KEY", "token")

    results, errors, usage = asyncio.run(
        analyzer._analyze_with_gemini(
            object(),
            [{"title": "医保新规", "url": "u1", "source": "govcn_policy", "timestamp": "", "raw_snippet": ""}],
        )
    )

    assert errors == []
    assert results[0]["title"] == "医保新规"
    assert usage["provider"] == "google"
