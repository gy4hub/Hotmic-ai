from pipeline.backtest import _daily_replay, _dedupe_daily_candidates, _selection_metrics


def test_selection_metrics_capture_diversity_and_risk():
    days = [
        [
            {"topic_line_primary": "public_issue", "content_role": "spread", "topic_cluster": "医保报销"},
            {"topic_line_primary": "family_anxiety", "content_role": "save", "topic_cluster": "儿童用药"},
            {"topic_line_primary": "consumer_scam", "content_role": "followup", "topic_cluster": "保健品骗局"},
        ],
        [
            {
                "topic_line_primary": "family_anxiety",
                "content_role": "spread",
                "topic_cluster": "儿童用药",
                "compliance_risk": "high",
                "actionability_risk": "low",
            },
            {
                "topic_line_primary": "family_anxiety",
                "content_role": "spread",
                "topic_cluster": "儿童用药",
                "reject_type": "quarantine",
            },
        ],
    ]

    metrics = _selection_metrics(days)

    assert metrics["days"] == 2
    assert metrics["line_diversity_pass_rate"] == 0.5
    assert metrics["role_diversity_pass_rate"] == 0.5
    assert metrics["cluster_diversity_pass_rate"] == 0.5
    assert metrics["high_risk_selected_count"] == 1
    assert metrics["rejected_selected_count"] == 1


def test_daily_replay_reports_slot_changes():
    old_selected = [
        {"title": "题目A", "topic_line_primary": "public_issue", "content_role": "spread"},
        {"title": "题目B", "topic_line_primary": "family_anxiety", "content_role": "save"},
    ]
    new_selected = [
        {"title": "题目A", "topic_line_primary": "public_issue", "content_role": "spread"},
        {"title": "题目C", "topic_line_primary": "consumer_scam", "content_role": "followup"},
    ]

    replay = _daily_replay("2026-03-18", old_selected, new_selected)

    assert replay["date"] == "2026-03-18"
    assert replay["changed_slots"] == 1
    assert replay["old_titles"] == ["题目A", "题目B"]
    assert replay["new_titles"] == ["题目A", "题目C"]


def test_dedupe_daily_candidates_keeps_best_scoring_variant():
    candidates = [
        {"topic_id": "abc123_30", "title": "同一题", "score_total": 4.2},
        {"topic_id": "abc123_36", "title": "同一题", "score_total": 4.8},
        {"topic_id": "other", "title": "另一题", "score_total": 4.0},
    ]

    deduped = _dedupe_daily_candidates(candidates)

    assert len(deduped) == 2
    assert deduped[0]["topic_id"] == "abc123_36"
