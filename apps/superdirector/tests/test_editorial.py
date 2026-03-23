from pipeline import editorial


def test_normalize_editorial_item_maps_cluster_to_controlled_vocab():
    topic = {
        "title": "315曝光外泌体美容骗局",
        "source": "wechat_rss",
        "raw_snippet": "外泌体 美容 骗局 真相",
    }
    item = {
        "summary": "315 曝光外泌体营销乱象",
        "topic_cluster": "外泌体 美容 骗局 真相",
        "content_role": "spread",
    }

    normalized = editorial.normalize_editorial_item(topic, item)

    assert normalized["topic_cluster"] == "抗衰骗局"
    assert normalized["topic_line_primary"] in {"consumer_scam", "family_anxiety"}


def test_normalize_editorial_item_downgrades_followup_without_parent():
    topic = {"title": "评论区都在问孩子退烧药怎么选", "source": "wechat_rss"}
    item = {"content_role": "followup"}

    normalized = editorial.normalize_editorial_item(topic, item)

    assert normalized["content_role"] == "save"


def test_normalize_editorial_item_prefers_family_anxiety_for_child_drug_safety():
    topic = {
        "title": "多款口服液被查出污染！儿童退烧药、止咳糖浆中招",
        "source": "who_alerts",
        "raw_snippet": "家长需要检查药盒与生产批号",
    }
    item = {
        "summary": "儿童常用退烧药与止咳糖浆涉污染，家长应立即检查批号与药盒。",
        "topic_cluster": "假药 / 劣药",
    }

    normalized = editorial.normalize_editorial_item(topic, item)

    assert normalized["topic_line_primary"] == "family_anxiety"
    assert normalized["content_role"] == "save"
    assert normalized["zhang_auntie_value"] in {"forward", "watch"}
    assert normalized["li_jie_value"] == "save"


def test_normalize_editorial_item_infers_creator_fit_and_dual_audience_values():
    topic = {
        "title": "进了医保，为什么医院还是开不出来？",
        "source": "wechat_rss",
        "raw_snippet": "国谈药进院难，患者用不上。",
    }
    item = {
        "summary": "这不是药价问题，而是医院、双通道和支付路径的几道门。",
        "topic_cluster": "医保进院难",
    }

    normalized = editorial.normalize_editorial_item(topic, item)

    assert normalized["creator_fit"] == "strong"
    assert normalized["li_jie_value"] == "save"
    assert normalized["zhang_auntie_value"] in {"forward", "watch"}


def test_medical_advice_style_title_is_quarantined_and_high_risk():
    topic = {
        "title": "儿童止咳祛痰，这7类药该怎么用？",
        "source": "wechat_rss",
        "raw_snippet": "面向家长的儿童用药科普。",
    }
    item = {
        "summary": "讲成分分类、禁忌和疗效差异。",
        "topic_cluster": "儿童用药",
    }

    normalized = editorial.normalize_editorial_item(topic, item)

    assert normalized["reject_type"] == "quarantine"
    assert normalized["compliance_risk"] == "high"
    assert normalized["actionability_risk"] == "high"


def test_prescription_quick_reference_title_is_quarantined():
    topic = {
        "title": "建议收藏！国内减重药处方速查（含滴定细节）",
        "source": "wechat_rss",
        "raw_snippet": "涉及处方药使用流程与滴定节奏。",
    }
    item = {
        "summary": "整理处方速查与滴定细节，方便用户快速对照。",
        "topic_cluster": "司美格鲁肽灰市",
    }

    normalized = editorial.normalize_editorial_item(topic, item)

    assert normalized["reject_type"] == "quarantine"
    assert normalized["compliance_risk"] == "high"
    assert normalized["actionability_risk"] == "high"


def test_health_panic_title_is_quarantined():
    topic = {
        "title": "你的肝，就是这样一口一口坏掉的（不是喝酒）",
        "source": "wechat_rss",
        "raw_snippet": "标题强情绪，但缺少明确权威事实锚点。",
    }
    item = {
        "summary": "更像泛养生恐吓式表达，容易引发焦虑转发。",
        "topic_cluster": "家庭医疗误区",
    }

    normalized = editorial.normalize_editorial_item(topic, item)

    assert normalized["reject_type"] == "quarantine"


def test_narrow_specialty_topic_does_not_overclaim_family_forward_value():
    topic = {
        "title": "全国首个！国产平台PGT-A试剂盒获批",
        "source": "wechat_rss",
        "raw_snippet": "辅助生殖高端环节，涉及胚胎植入前遗传学检测。",
    }
    item = {
        "summary": "家族群常转试管避坑，但题材仍偏辅助生殖细分。",
        "topic_cluster": "罕见病 / 高价药支付",
    }

    normalized = editorial.normalize_editorial_item(topic, item)

    assert normalized["creator_fit"] == "medium"
    assert normalized["zhang_auntie_value"] != "forward"


def test_normalize_editorial_item_hard_rejects_offtopic_title_even_if_summary_mentions_medical():
    topic = {
        "title": "龙虾掀起裁员潮，工作牛马怎么办？",
        "source": "wechat_rss",
        "raw_snippet": "医保断缴 家庭收入变化",
    }
    item = {
        "summary": "借就业焦虑嫁接家庭医疗支付压力。",
        "keywords": ["裁员潮", "医保断缴"],
        "topic_cluster": "医保报销",
    }

    normalized = editorial.normalize_editorial_item(topic, item)

    assert normalized["reject_type"] == "hard_reject"
    assert normalized["topic_line_primary"] == "rejected"


def test_select_topics_for_output_respects_phase2_filters():
    candidates = [
        {
            "topic_id": "a",
            "title": "医保报销新规",
            "source": "wechat_rss",
            "score_total": 4.8,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "医保报销",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "b",
            "title": "儿童退烧药三招避坑",
            "source": "baidu_search",
            "score_total": 4.5,
            "topic_line_primary": "family_anxiety",
            "content_role": "save",
            "topic_cluster": "儿童用药",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "c",
            "title": "NAD+又来收智商税了",
            "source": "brave_search",
            "score_total": 4.4,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "NAD+",
            "reject_type": "none",
            "compliance_risk": "high",
            "actionability_risk": "low",
        },
        {
            "topic_id": "d",
            "title": "315曝光保健品骗局",
            "source": "who_alerts",
            "score_total": 4.3,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "保健品骗局",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    selected, meta = editorial.select_topics_for_output(candidates, [], phase=2, top_n=3)

    ids = {item["topic_id"] for item in selected}
    assert "c" not in ids
    assert "a" in ids and "b" in ids
    assert meta["mode"] in {"editorial_selection", "fallback"}


def test_select_topics_for_output_uses_diversified_fallback_when_no_valid_combo():
    candidates = [
        {
            "topic_id": "a",
            "title": "医保报销新规",
            "source": "wechat_rss",
            "score_total": 4.8,
            "topic_line_primary": "family_anxiety",
            "content_role": "spread",
            "topic_cluster": "医保报销",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "b",
            "title": "药价又涨，家庭更难扛",
            "source": "stat_pharma",
            "score_total": 4.6,
            "topic_line_primary": "family_anxiety",
            "content_role": "spread",
            "topic_cluster": "药价变化",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "c",
            "title": "儿童退烧药污染警报",
            "source": "baidu_search",
            "score_total": 4.2,
            "topic_line_primary": "family_anxiety",
            "content_role": "spread",
            "topic_cluster": "儿童用药",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "d",
            "title": "药监局加强药品追溯",
            "source": "nmpa_news",
            "score_total": 4.0,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "医疗监管变化",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    selected, meta = editorial.select_topics_for_output(candidates, [], phase=2, top_n=3)

    ids = {item["topic_id"] for item in selected}
    assert "d" in ids
    assert "a" in ids
    assert meta["mode"] == "fallback_diversified"


def test_select_topics_for_output_orders_selected_topics_for_editorial_mix():
    candidates = [
        {
            "topic_id": "a",
            "title": "315点名外泌体",
            "source": "wechat_rss",
            "score_total": 4.9,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "抗衰骗局",
            "reject_type": "none",
            "compliance_risk": "medium",
            "actionability_risk": "low",
        },
        {
            "topic_id": "b",
            "title": "进了医保，为什么医院还是开不出来？",
            "source": "baidu_search",
            "score_total": 4.4,
            "topic_line_primary": "public_issue",
            "content_role": "save",
            "topic_cluster": "医保进院难",
            "decision_impact_level": "high",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "c",
            "title": "孩子睡不着就吃褪黑素？",
            "source": "wechat_rss",
            "score_total": 4.5,
            "topic_line_primary": "family_anxiety",
            "content_role": "spread",
            "topic_cluster": "儿童用药",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    selected, _meta = editorial.select_topics_for_output(candidates, [], phase=2, top_n=3)

    top3_roles = {item["content_role"] for item in selected[:3]}
    top3_lines = {item["topic_line_primary"] for item in selected[:3]}
    assert "save" in top3_roles
    assert len(top3_lines) >= 2


def test_international_public_issue_gets_domestic_relevance_penalty():
    candidates = [
        {
            "topic_id": "intl",
            "title": "英国突发流脑疫情，两死多例",
            "summary": "英国肯特郡出现聚集性疫情，学生夜店活动后集中感染。",
            "source": "rss_nyt_health",
            "score_total": 4.6,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "药品安全警报",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "domestic",
            "title": "国家发文，医疗器械全面实名制",
            "summary": "国家发文，关系家用器械购买与备案。",
            "source": "wechat_rss",
            "score_total": 4.35,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "医疗监管变化",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    enriched = editorial.enrich_editorial_scores(candidates, [])
    by_id = {item["topic_id"]: item for item in enriched}

    assert by_id["intl"]["domestic_relevance_penalty"] > 0
    assert by_id["domestic"]["domestic_relevance_penalty"] == 0
    assert by_id["domestic"]["editorial_priority_score"] > by_id["intl"]["editorial_priority_score"]


def test_select_topics_filters_international_public_issue_without_domestic_anchor():
    candidates = [
        {
            "topic_id": "intl_public",
            "title": "白宫硬推最惠国药价",
            "summary": "白宫推动美国药价法案，对国内药价暂无直接影响。",
            "source": "rss_stat_backup",
            "score_total": 4.5,
            "topic_line_primary": "public_issue",
            "content_role": "save",
            "topic_cluster": "医疗政策变化",
            "decision_impact_level": "low",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "domestic_family",
            "title": "孩子退烧药药盒先别扔",
            "source": "wechat_rss",
            "score_total": 4.2,
            "topic_line_primary": "family_anxiety",
            "content_role": "save",
            "topic_cluster": "儿童用药",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "consumer",
            "title": "假药警报又来了",
            "source": "who_alerts",
            "score_total": 4.7,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "假药 / 劣药",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "domestic_public",
            "title": "国家药监局新规落地",
            "source": "wechat_rss",
            "score_total": 4.0,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "医疗监管变化",
            "decision_impact_level": "high",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    selected, _meta = editorial.select_topics_for_output(candidates, [], phase=2, top_n=3)
    ids = {item["topic_id"] for item in selected}

    assert "intl_public" not in ids


def test_enrich_editorial_scores_adds_positive_history_perf_bonus():
    candidates = [
        {
            "topic_id": "current",
            "title": "为什么总有人被外泌体概念带偏？",
            "source": "wechat_rss",
            "score_total": 4.2,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "抗衰骗局",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        }
    ]
    recent_topics = [
        {
            "topic_cluster": "抗衰骗局",
            "publish_status": "published",
            "publish_at": "2026-03-10T20:00:00+08:00",
            "perf_watch_rate": 45.0,
        },
        {
            "topic_cluster": "抗衰骗局",
            "publish_status": "published",
            "publish_at": "2026-03-16T20:00:00+08:00",
            "perf_watch_rate": 42.0,
        },
    ]

    enriched = editorial.enrich_editorial_scores(candidates, recent_topics)

    assert enriched[0]["performance_feedback_bonus"] == 0.1
    assert "history_perf=+0.10" in enriched[0]["selection_rank_reason"]


def test_enrich_editorial_scores_adds_negative_history_perf_bonus():
    candidates = [
        {
            "topic_id": "low-perf",
            "title": "医保新规到底改了什么？",
            "source": "wechat_rss",
            "score_total": 4.2,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "医疗政策变化",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "neutral",
            "title": "家庭药箱先别乱扔说明书",
            "source": "wechat_rss",
            "score_total": 4.2,
            "topic_line_primary": "family_anxiety",
            "content_role": "save",
            "topic_cluster": "家庭药箱",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]
    recent_topics = [
        {
            "topic_cluster": "医疗政策变化",
            "publish_status": "published",
            "publish_at": "2026-03-08T20:00:00+08:00",
            "perf_watch_rate": 18.0,
        },
        {
            "topic_cluster": "医疗政策变化",
            "publish_status": "published",
            "publish_at": "2026-03-12T20:00:00+08:00",
            "perf_watch_rate": 16.5,
        },
    ]

    baseline = editorial.enrich_editorial_scores(candidates, [])
    enriched = editorial.enrich_editorial_scores(candidates, recent_topics)
    baseline_by_id = {item["topic_id"]: item for item in baseline}
    by_id = {item["topic_id"]: item for item in enriched}

    assert by_id["low-perf"]["performance_feedback_bonus"] == -0.08
    assert by_id["neutral"]["performance_feedback_bonus"] == 0.0
    assert by_id["low-perf"]["editorial_priority_score"] < baseline_by_id["low-perf"]["editorial_priority_score"]


def test_select_topics_filters_weak_public_issue_bulletin_without_household_angle():
    candidates = [
        {
            "topic_id": "weak_public",
            "title": "国家医保局：2025年共追回医保基金342亿元",
            "summary": "医保监管成果通报。",
            "source": "wechat_rss",
            "score_total": 4.55,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "医保报销",
            "decision_impact_level": "medium",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "family",
            "title": "315点名外泌体",
            "summary": "老人健康消费骗局",
            "source": "wechat_rss",
            "score_total": 4.7,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "抗衰骗局",
            "decision_impact_level": "high",
            "reject_type": "none",
            "compliance_risk": "medium",
            "actionability_risk": "low",
        },
        {
            "topic_id": "save_public",
            "title": "进了医保，为什么医院还是开不出来？",
            "summary": "创新药进院难，患者还是用不上。",
            "source": "baidu_search",
            "score_total": 4.35,
            "topic_line_primary": "public_issue",
            "content_role": "save",
            "topic_cluster": "医保进院难",
            "decision_impact_level": "high",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    selected, _meta = editorial.select_topics_for_output(candidates, [], phase=2, top_n=3)
    ids = {item["topic_id"] for item in selected}

    assert "save_public" in ids
    assert "weak_public" not in ids


def test_local_shareability_bonus_prefers_315_family_scam_topics():
    candidates = [
        {
            "topic_id": "private_marketing",
            "title": "315私域营销专家之谜：别让健康讲座掏空老人的养老金",
            "summary": "老人被引流进私域健康讲座后高价买保健品。",
            "source": "wechat_rss",
            "score_total": 4.35,
            "topic_line_primary": "family_anxiety",
            "content_role": "spread",
            "topic_cluster": "保健品骗局",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "generic",
            "title": "某国际研究提示老年人睡眠风险",
            "summary": "研究提示睡眠问题值得关注。",
            "source": "rss_nyt_health",
            "score_total": 4.35,
            "topic_line_primary": "family_anxiety",
            "content_role": "spread",
            "topic_cluster": "老年人健康风险",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    enriched = editorial.enrich_editorial_scores(candidates, [])
    by_id = {item["topic_id"]: item for item in enriched}

    assert by_id["private_marketing"]["local_shareability_bonus"] > 0
    assert by_id["private_marketing"]["editorial_priority_score"] > by_id["generic"]["editorial_priority_score"]


def test_policy_translation_topics_are_capped_to_one_in_phase2_selection():
    candidates = [
        {
            "topic_id": "policy_a",
            "title": "2026医保新规：这5种费用以后得自己掏",
            "summary": "目录和起付线变化解读。",
            "source": "wechat_rss",
            "score_total": 4.7,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "医保报销",
            "creator_fit": "medium",
            "li_jie_value": "click",
            "zhang_auntie_value": "watch",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "policy_b",
            "title": "双通道名单扩容：哪些药现在能买了",
            "summary": "管理名单与政策变化。",
            "source": "govcn_policy",
            "score_total": 4.68,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "医保报销",
            "creator_fit": "medium",
            "li_jie_value": "click",
            "zhang_auntie_value": "watch",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "family",
            "title": "315点名外泌体：为什么反而最该警惕？",
            "summary": "老人健康消费决策题。",
            "source": "wechat_rss",
            "score_total": 4.55,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "抗衰骗局",
            "creator_fit": "strong",
            "li_jie_value": "save",
            "zhang_auntie_value": "forward",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "save_public",
            "title": "进了医保，为什么医院还是开不出来？",
            "summary": "不是技术bug，而是医院和支付之间还有几道门。",
            "source": "baidu_search",
            "score_total": 4.5,
            "topic_line_primary": "public_issue",
            "content_role": "save",
            "topic_cluster": "医保进院难",
            "creator_fit": "strong",
            "li_jie_value": "save",
            "zhang_auntie_value": "forward",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    selected, _meta = editorial.select_topics_for_output(candidates, [], phase=2, top_n=3)
    policy_count = sum(1 for item in selected if item.get("policy_translation_penalty", 0) > 0)

    assert policy_count <= 1


def test_who_fake_drug_alert_gets_extra_penalty_without_domestic_anchor():
    candidates = [
        {
            "topic_id": "who_fake_ibrance",
            "title": "假爱博新被WHO点名！乳腺癌靶向药有仿冒货",
            "summary": "WHO 在多国发布假冒 IBRANCE 警报。",
            "source": "who_alerts",
            "score_total": 4.8,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "假药 / 劣药",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "domestic_exosome",
            "title": "315点名外泌体：没有批文，没有临床，为何还敢卖3针6万",
            "summary": "央视315曝光外泌体营销乱象，直击家庭健康消费决策。",
            "source": "wechat_rss",
            "score_total": 4.7,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "抗衰骗局",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    enriched = editorial.enrich_editorial_scores(candidates, [])
    by_id = {item["topic_id"]: item for item in enriched}

    assert by_id["who_fake_ibrance"]["domestic_relevance_penalty"] >= 0.6
    assert by_id["domestic_exosome"]["editorial_priority_score"] > by_id["who_fake_ibrance"]["editorial_priority_score"]


def test_source_preference_bonus_prefers_wechat_and_baidu_over_macro_and_international_feeds():
    candidates = [
        {
            "topic_id": "wechat",
            "title": "315点名外泌体：为什么反而最该警惕？",
            "summary": "家庭决策与防骗场景很强。",
            "source": "wechat_rss",
            "score_total": 4.2,
            "topic_line_primary": "consumer_scam",
            "content_role": "spread",
            "topic_cluster": "抗衰骗局",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "baidu",
            "title": "进了医保，为什么医院还是开不出来？",
            "summary": "患者和家属都关心的现实问题。",
            "source": "baidu_search",
            "score_total": 4.2,
            "topic_line_primary": "public_issue",
            "content_role": "save",
            "topic_cluster": "医保进院难",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "stats",
            "title": "2025年居民消费价格数据发布",
            "summary": "宏观统计口径更新。",
            "source": "rss_stats_release",
            "score_total": 4.2,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "药价变化",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "intl",
            "title": "纽约最新研究提示睡眠风险",
            "summary": "国际研究背景，家庭现实映射较弱。",
            "source": "rss_nyt_health",
            "score_total": 4.2,
            "topic_line_primary": "family_anxiety",
            "content_role": "spread",
            "topic_cluster": "老年人健康风险",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    enriched = editorial.enrich_editorial_scores(candidates, [])
    by_id = {item["topic_id"]: item for item in enriched}

    assert by_id["wechat"]["source_preference_bonus"] > by_id["baidu"]["source_preference_bonus"] > 0
    assert by_id["stats"]["source_preference_bonus"] < 0
    assert by_id["intl"]["source_preference_bonus"] < 0


def test_policy_translation_penalty_hits_policy_explainer_but_not_household_pain_public_issue():
    candidates = [
        {
            "topic_id": "policy",
            "title": "2026 外商独资医院爆发：医保能不能报？",
            "summary": "试点政策继续扩围，关注报销比例和起付线。",
            "source": "wechat_rss",
            "score_total": 4.2,
            "topic_line_primary": "public_issue",
            "content_role": "spread",
            "topic_cluster": "医疗政策变化",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
        {
            "topic_id": "pain",
            "title": "进了医保，为什么医院还是开不出来？",
            "summary": "患者不是不想用，是进院和支付这几道门还没过去。",
            "source": "wechat_rss",
            "score_total": 4.2,
            "topic_line_primary": "public_issue",
            "content_role": "save",
            "topic_cluster": "医保进院难",
            "reject_type": "none",
            "compliance_risk": "low",
            "actionability_risk": "low",
        },
    ]

    enriched = editorial.enrich_editorial_scores(candidates, [])
    by_id = {item["topic_id"]: item for item in enriched}

    assert by_id["policy"]["policy_translation_penalty"] > 0
    assert by_id["pain"]["policy_translation_penalty"] == 0
    assert by_id["pain"]["editorial_priority_score"] > by_id["policy"]["editorial_priority_score"]
