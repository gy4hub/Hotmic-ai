from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tools import api_routes


class DummyRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def test_schedule_update_returns_latest_jobs(monkeypatch):
    updated = []

    async def fake_update_schedule_job(_session, job_id, **kwargs):
        updated.append((job_id, kwargs))
        return SimpleNamespace(
            job_id=job_id,
            cron_hour=kwargs.get("hour", 7),
            cron_minute=kwargs.get("minute", 0),
            enabled=1,
            description="每日选题早报",
            last_run_at=None,
            last_run_status=None,
            last_run_error=None,
            updated_at="2026-03-17T07:00:00Z",
        )

    async def fake_list_schedule_jobs():
        return [
            SimpleNamespace(
                job_id="morning_briefing",
                cron_hour=7,
                cron_minute=0,
                enabled=1,
                description="每日选题早报",
                last_run_at=None,
                last_run_status=None,
                last_run_error=None,
                updated_at="2026-03-17T07:00:00Z",
            )
        ]

    async def fake_refresh(job_id):
        return job_id

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(api_routes.crud, "update_schedule_job", fake_update_schedule_job)
    monkeypatch.setattr(api_routes, "list_schedule_jobs", fake_list_schedule_jobs)
    monkeypatch.setattr(api_routes, "refresh_schedule_job", fake_refresh)
    monkeypatch.setattr(api_routes, "AsyncSessionLocal", lambda: DummySession())

    result = asyncio.run(
        api_routes.schedule_update(
            DummyRequest({"job_id": "morning_briefing", "hour": 7, "minute": 0})
        )
    )

    assert updated[0][0] == "morning_briefing"
    assert result["jobs"][0]["hour"] == 7
    assert result["jobs"][0]["minute"] == 0


def test_schedule_run_returns_job_execution(monkeypatch):
    async def fake_list_schedule_jobs():
        return [
            SimpleNamespace(
                job_id="collector_morning",
                cron_hour=8,
                cron_minute=0,
                enabled=1,
                description="早间数据采集",
                last_run_at=None,
                last_run_status=None,
                last_run_error=None,
                updated_at=None,
            )
        ]

    async def fake_run(job_id):
        return {"job_id": job_id, "status": "ok"}

    monkeypatch.setattr(api_routes, "list_schedule_jobs", fake_list_schedule_jobs)
    monkeypatch.setattr(api_routes, "run_schedule_job_now", fake_run)

    result = asyncio.run(api_routes.schedule_run("collector_morning"))

    assert result["job_id"] == "collector_morning"
    assert result["status"] == "ok"
