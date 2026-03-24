from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pipeline import pipeline


class DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_run_pipeline_mock_orchestrates_and_persists(monkeypatch):
    finalized = []
    inserted_details = []

    async def fake_fail_stale_pipeline_runs(_session, *, stale_after_seconds):
        assert stale_after_seconds > 0
        return 0

    async def fake_create_pipeline_run(_session):
        return SimpleNamespace(id=7)

    async def fake_list_pending_raw_candidates(_session):
        return []

    async def fake_collect_topics(_int_client, _ext_client, pending_items=None):
        assert pending_items == []
        return ([{"topic_id": "t1", "title": "医保新规", "source": "wechat_rss"}], [])

    async def fake_analyze_topics(_ext_client, _int_client, collected):
        assert len(collected) == 1
        return (
            [{"topic_id": "t1", "title": "医保新规", "source": "wechat_rss", "score_total": 4.5}],
            [],
            {"provider": "qwen", "model": "qwen-plus", "endpoint": "chat.completions", "input_tokens": 20, "output_tokens": 10},
        )

    def fake_score_topics(analyzed):
        assert analyzed[0]["topic_id"] == "t1"
        return (
            [{"topic_id": "t1", "title": "医保新规", "source": "wechat_rss", "score_total": 4.5}],
            [{"topic_id": "t1", "dimension": "emotion", "raw_score": 4.0, "weighted_score": 4.0, "platform": "douyin"}],
        )

    async def fake_get_recent_editorial_topics(_session, *, since_days, limit):
        assert since_days >= 7
        assert limit == 200
        return []

    def fake_select_topics_for_output(scored, recent_topics, top_n):
        assert recent_topics == []
        assert top_n == pipeline.TOP_N
        return (scored, {"mode": "editorial_selection"})

    def fake_quality_gate(_topics, _raw_count):
        return True, "通过"

    async def fake_generate_frames(_ext_client, _int_client, topics):
        return (
            [
                {
                    **topics[0],
                    "frame": {"hook": "h", "outline": ["1", "2", "3", "4"], "cta": "go"},
                }
            ],
            [],
            {"provider": "qwen", "model": "qwen-plus", "endpoint": "chat.completions", "input_tokens": 6, "output_tokens": 3},
        )

    def fake_frame_quality_gate(_topic):
        return True, "ok"

    async def fake_insert_topics(_session, topics):
        assert topics[0]["frame_status"] == "passed"
        return [SimpleNamespace(id=101, topic_id="t1")]

    async def fake_insert_score_details(_session, details):
        inserted_details.extend(details)

    def fake_estimate_cost_usd(_provider, _model, _input_tokens, _output_tokens):
        return 0.01

    async def fake_log_cost(*args, **kwargs):
        return None

    async def fake_sync_topics_to_bitable(_client, topics):
        assert topics[0]["topic_id"] == "t1"
        return {"queued_tasks": [], "errors": []}

    async def fake_enqueue_bitable_sync_tasks(_session, tasks):
        raise AssertionError("should not enqueue tasks")

    async def fake_log_system(*args, **kwargs):
        return None

    async def fake_finalize_pipeline_run(_session, *, run_id, status, topics_count, raw_item_count, error_count, total_tokens, total_cost, errors):
        finalized.append(
            {
                "run_id": run_id,
                "status": status,
                "topics_count": topics_count,
                "raw_item_count": raw_item_count,
                "error_count": error_count,
                "total_tokens": total_tokens,
                "total_cost": total_cost,
                "errors": list(errors),
            }
        )

    async def fake_mark_raw_candidates_consumed(_session, ids):
        assert ids == []

    monkeypatch.setattr(pipeline, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(pipeline, "TOP_N", 1)
    monkeypatch.setattr(pipeline.crud, "fail_stale_pipeline_runs", fake_fail_stale_pipeline_runs)
    monkeypatch.setattr(pipeline.crud, "create_pipeline_run", fake_create_pipeline_run)
    monkeypatch.setattr(pipeline.crud, "list_pending_raw_candidates", fake_list_pending_raw_candidates)
    monkeypatch.setattr(pipeline, "collect_topics", fake_collect_topics)
    monkeypatch.setattr(pipeline, "analyze_topics", fake_analyze_topics)
    monkeypatch.setattr(pipeline, "score_topics", fake_score_topics)
    monkeypatch.setattr(pipeline.crud, "get_recent_editorial_topics", fake_get_recent_editorial_topics)
    monkeypatch.setattr(pipeline, "select_topics_for_output", fake_select_topics_for_output)
    monkeypatch.setattr(pipeline, "quality_gate", fake_quality_gate)
    monkeypatch.setattr(pipeline, "generate_frames", fake_generate_frames)
    monkeypatch.setattr(pipeline, "frame_quality_gate", fake_frame_quality_gate)
    monkeypatch.setattr(pipeline.crud, "insert_topics", fake_insert_topics)
    monkeypatch.setattr(pipeline.crud, "insert_score_details", fake_insert_score_details)
    monkeypatch.setattr(pipeline, "estimate_cost_usd", fake_estimate_cost_usd)
    monkeypatch.setattr(pipeline.crud, "log_cost", fake_log_cost)
    monkeypatch.setattr(pipeline, "sync_topics_to_bitable", fake_sync_topics_to_bitable)
    monkeypatch.setattr(pipeline.crud, "enqueue_bitable_sync_tasks", fake_enqueue_bitable_sync_tasks)
    monkeypatch.setattr(pipeline.crud, "log_system", fake_log_system)
    monkeypatch.setattr(pipeline.crud, "finalize_pipeline_run", fake_finalize_pipeline_run)
    monkeypatch.setattr(pipeline.crud, "mark_raw_candidates_consumed", fake_mark_raw_candidates_consumed)

    app_state = SimpleNamespace(int_client=object(), ext_client=object())
    result = asyncio.run(pipeline.run_pipeline(app_state))

    assert result["run_id"] == 7
    assert result["editorial"]["mode"] == "editorial_selection"
    assert result["quality_gate"]["passed"] is True
    assert result["topics"][0]["frame_status"] == "passed"
    assert inserted_details[0]["topic_id"] == 101
    assert finalized[0]["status"] == "ok"
    assert finalized[0]["total_tokens"] == 39


def test_run_pipeline_uses_prefilter_when_enabled(monkeypatch):
    finalized = []
    observed = {"prefilter_input": None, "analyze_input": None}

    async def fake_fail_stale_pipeline_runs(_session, *, stale_after_seconds):
        return 0

    async def fake_create_pipeline_run(_session):
        return SimpleNamespace(id=8)

    async def fake_list_pending_raw_candidates(_session):
        return []

    async def fake_collect_topics(_int_client, _ext_client, pending_items=None):
        return (
            [
                {"topic_id": "t1", "title": "海外商业稿", "source": "rss_nyt_health"},
                {"topic_id": "t2", "title": "医保新规", "source": "govcn_policy"},
            ],
            [],
        )

    async def fake_prefilter_topics(_int_client, topics):
        observed["prefilter_input"] = [topic["topic_id"] for topic in topics]
        return (
            [topics[1]],
            [],
            {"provider": "qwen", "model": "qwen-plus", "endpoint": "chat.completions", "input_tokens": 8, "output_tokens": 2},
        )

    async def fake_analyze_topics(_ext_client, _int_client, collected):
        observed["analyze_input"] = [topic["topic_id"] for topic in collected]
        return (
            [{"topic_id": "t2", "title": "医保新规", "source": "govcn_policy", "score_total": 4.5}],
            [],
            {"provider": "qwen", "model": "qwen-max", "endpoint": "chat.completions", "input_tokens": 20, "output_tokens": 10},
        )

    def fake_score_topics(analyzed):
        return (analyzed, [])

    async def fake_get_recent_editorial_topics(_session, *, since_days, limit):
        return []

    def fake_select_topics_for_output(scored, recent_topics, top_n):
        return (scored, {"mode": "editorial_selection"})

    def fake_quality_gate(_topics, _raw_count):
        return True, "通过"

    async def fake_generate_frames(_ext_client, _int_client, topics):
        return (topics, [], {})

    def fake_frame_quality_gate(_topic):
        return True, "ok"

    async def fake_insert_topics(_session, topics):
        return [SimpleNamespace(id=102, topic_id="t2")]

    async def fake_insert_score_details(_session, details):
        return None

    def fake_estimate_cost_usd(_provider, _model, _input_tokens, _output_tokens):
        return 0.01

    async def fake_log_cost(*args, **kwargs):
        return None

    async def fake_sync_topics_to_bitable(_client, topics):
        return {"queued_tasks": [], "errors": []}

    async def fake_enqueue_bitable_sync_tasks(_session, tasks):
        return None

    async def fake_log_system(*args, **kwargs):
        return None

    async def fake_finalize_pipeline_run(_session, **kwargs):
        finalized.append(kwargs)

    async def fake_mark_raw_candidates_consumed(_session, ids):
        return None

    monkeypatch.setattr(pipeline, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(pipeline, "TOP_N", 1)
    monkeypatch.setattr(pipeline, "PREFILTER_ENABLED", True)
    monkeypatch.setattr(pipeline.crud, "fail_stale_pipeline_runs", fake_fail_stale_pipeline_runs)
    monkeypatch.setattr(pipeline.crud, "create_pipeline_run", fake_create_pipeline_run)
    monkeypatch.setattr(pipeline.crud, "list_pending_raw_candidates", fake_list_pending_raw_candidates)
    monkeypatch.setattr(pipeline, "collect_topics", fake_collect_topics)
    monkeypatch.setattr(pipeline, "prefilter_topics", fake_prefilter_topics)
    monkeypatch.setattr(pipeline, "analyze_topics", fake_analyze_topics)
    monkeypatch.setattr(pipeline, "score_topics", fake_score_topics)
    monkeypatch.setattr(pipeline.crud, "get_recent_editorial_topics", fake_get_recent_editorial_topics)
    monkeypatch.setattr(pipeline, "select_topics_for_output", fake_select_topics_for_output)
    monkeypatch.setattr(pipeline, "quality_gate", fake_quality_gate)
    monkeypatch.setattr(pipeline, "generate_frames", fake_generate_frames)
    monkeypatch.setattr(pipeline, "frame_quality_gate", fake_frame_quality_gate)
    monkeypatch.setattr(pipeline.crud, "insert_topics", fake_insert_topics)
    monkeypatch.setattr(pipeline.crud, "insert_score_details", fake_insert_score_details)
    monkeypatch.setattr(pipeline, "estimate_cost_usd", fake_estimate_cost_usd)
    monkeypatch.setattr(pipeline.crud, "log_cost", fake_log_cost)
    monkeypatch.setattr(pipeline, "sync_topics_to_bitable", fake_sync_topics_to_bitable)
    monkeypatch.setattr(pipeline.crud, "enqueue_bitable_sync_tasks", fake_enqueue_bitable_sync_tasks)
    monkeypatch.setattr(pipeline.crud, "log_system", fake_log_system)
    monkeypatch.setattr(pipeline.crud, "finalize_pipeline_run", fake_finalize_pipeline_run)
    monkeypatch.setattr(pipeline.crud, "mark_raw_candidates_consumed", fake_mark_raw_candidates_consumed)

    app_state = SimpleNamespace(int_client=object(), ext_client=object())
    result = asyncio.run(pipeline.run_pipeline(app_state))

    assert observed["prefilter_input"] == ["t1", "t2"]
    assert observed["analyze_input"] == ["t2"]
    assert result["topics"][0]["topic_id"] == "t2"
    assert finalized[0]["total_tokens"] == 40


def test_run_pipeline_frames_only_top_n_and_marks_rest_skipped(monkeypatch):
    finalized = []
    observed = {"framed_ids": None, "inserted_topics": None, "synced_ids": None}

    async def fake_fail_stale_pipeline_runs(_session, *, stale_after_seconds):
        return 0

    async def fake_create_pipeline_run(_session):
        return SimpleNamespace(id=9)

    async def fake_list_pending_raw_candidates(_session):
        return []

    async def fake_collect_topics(_int_client, _ext_client, pending_items=None):
        return ([{"topic_id": f"t{i}", "title": f"题目{i}", "source": "wechat_rss"} for i in range(1, 4)], [])

    async def fake_analyze_topics(_ext_client, _int_client, collected):
        return (collected, [], {})

    def fake_score_topics(analyzed):
        return (analyzed, [])

    async def fake_get_recent_editorial_topics(_session, *, since_days, limit):
        return []

    def fake_select_topics_for_output(scored, recent_topics, top_n):
        return (scored, {"mode": "editorial_selection"})

    def fake_quality_gate(_topics, _raw_count):
        return True, "通过"

    async def fake_generate_frames(_ext_client, _int_client, topics):
        observed["framed_ids"] = [topic["topic_id"] for topic in topics]
        return (
            [
                {
                    **topic,
                    "frame": {"hook": "短 hook", "outline": ["第一条足够长", "第二条足够长", "第三条足够长", "第四条足够长"], "cta": "转发"},
                    "frame_status": "passed",
                }
                for topic in topics
            ],
            [],
            {},
        )

    def fake_frame_quality_gate(_topic):
        return True, "ok"

    async def fake_insert_topics(_session, topics):
        observed["inserted_topics"] = topics
        return [SimpleNamespace(id=idx, topic_id=topic["topic_id"]) for idx, topic in enumerate(topics, start=201)]

    async def fake_insert_score_details(_session, details):
        return None

    def fake_estimate_cost_usd(_provider, _model, _input_tokens, _output_tokens):
        return 0.0

    async def fake_log_cost(*args, **kwargs):
        return None

    async def fake_sync_topics_to_bitable(_client, topics):
        observed["synced_ids"] = [topic["topic_id"] for topic in topics]
        return {"queued_tasks": [], "errors": []}

    async def fake_enqueue_bitable_sync_tasks(_session, tasks):
        return None

    async def fake_log_system(*args, **kwargs):
        return None

    async def fake_finalize_pipeline_run(_session, **kwargs):
        finalized.append(kwargs)

    async def fake_mark_raw_candidates_consumed(_session, ids):
        return None

    monkeypatch.setattr(pipeline, "AsyncSessionLocal", lambda: DummySession())
    monkeypatch.setattr(pipeline, "TOP_N", 3)
    monkeypatch.setattr(pipeline, "FRAME_TOP_N", 2)
    monkeypatch.setattr(pipeline, "PREFILTER_ENABLED", False)
    monkeypatch.setattr(pipeline.crud, "fail_stale_pipeline_runs", fake_fail_stale_pipeline_runs)
    monkeypatch.setattr(pipeline.crud, "create_pipeline_run", fake_create_pipeline_run)
    monkeypatch.setattr(pipeline.crud, "list_pending_raw_candidates", fake_list_pending_raw_candidates)
    monkeypatch.setattr(pipeline, "collect_topics", fake_collect_topics)
    monkeypatch.setattr(pipeline, "analyze_topics", fake_analyze_topics)
    monkeypatch.setattr(pipeline, "score_topics", fake_score_topics)
    monkeypatch.setattr(pipeline.crud, "get_recent_editorial_topics", fake_get_recent_editorial_topics)
    monkeypatch.setattr(pipeline, "select_topics_for_output", fake_select_topics_for_output)
    monkeypatch.setattr(pipeline, "quality_gate", fake_quality_gate)
    monkeypatch.setattr(pipeline, "generate_frames", fake_generate_frames)
    monkeypatch.setattr(pipeline, "frame_quality_gate", fake_frame_quality_gate)
    monkeypatch.setattr(pipeline.crud, "insert_topics", fake_insert_topics)
    monkeypatch.setattr(pipeline.crud, "insert_score_details", fake_insert_score_details)
    monkeypatch.setattr(pipeline, "estimate_cost_usd", fake_estimate_cost_usd)
    monkeypatch.setattr(pipeline.crud, "log_cost", fake_log_cost)
    monkeypatch.setattr(pipeline, "sync_topics_to_bitable", fake_sync_topics_to_bitable)
    monkeypatch.setattr(pipeline.crud, "enqueue_bitable_sync_tasks", fake_enqueue_bitable_sync_tasks)
    monkeypatch.setattr(pipeline.crud, "log_system", fake_log_system)
    monkeypatch.setattr(pipeline.crud, "finalize_pipeline_run", fake_finalize_pipeline_run)
    monkeypatch.setattr(pipeline.crud, "mark_raw_candidates_consumed", fake_mark_raw_candidates_consumed)

    app_state = SimpleNamespace(int_client=object(), ext_client=object())
    result = asyncio.run(pipeline.run_pipeline(app_state))

    assert observed["framed_ids"] == ["t1", "t2"]
    assert observed["synced_ids"] == ["t1", "t2", "t3"]
    assert [topic["topic_id"] for topic in observed["inserted_topics"]] == ["t1", "t2", "t3"]
    assert result["topics"][2]["frame_status"] == "skipped"
    assert result["topics"][2]["frame_rejection_reason"] == "skipped_by_frame_limit"
    assert finalized[0]["topics_count"] == 3
    assert finalized[0]["status"] == "ok"
