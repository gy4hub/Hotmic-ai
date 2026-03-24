from __future__ import annotations

import asyncio
from types import SimpleNamespace

import scheduler


def test_feedback_weekly_job_registered():
    job_ids = {job["job_id"] for job in scheduler.DEFAULT_SCHEDULE_JOBS}
    assert "feedback_weekly" in job_ids


def test_run_job_feedback_weekly_uses_ext_client(monkeypatch):
    app_state = SimpleNamespace(ext_client=object())
    scheduler._app_state = app_state

    async def fake_run_feedback_weekly_cycle(client):
        assert client is app_state.ext_client
        return {"status": "ok", "eligible_topics": 6}

    monkeypatch.setattr(scheduler, "run_feedback_weekly_cycle", fake_run_feedback_weekly_cycle)

    result = asyncio.run(scheduler._run_job("feedback_weekly"))

    assert result["status"] == "ok"
    assert result["result"]["eligible_topics"] == 6


def test_start_scheduler_respects_disabled_switch(monkeypatch):
    monkeypatch.setattr(scheduler, "SCHEDULER_ENABLED", False)

    result = asyncio.run(scheduler.start_scheduler(SimpleNamespace()))

    assert result is None
