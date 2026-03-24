from __future__ import annotations

import asyncio
from types import SimpleNamespace

import api.routes as api_routes


class DummyRequest:
    def __init__(self):
        self.app = SimpleNamespace(state=SimpleNamespace(int_client=object()))


class DummySession:
    def __init__(self, display_run, active_run):
        self.display_run = display_run
        self.active_run = active_run
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        self.calls += 1

        class DummyResult:
            def __init__(self, value):
                self.value = value

            def scalar_one_or_none(self):
                return self.value

            def all(self):
                return [("competitor_老蒋巨靠谱",), ("evergreen",)]

        if self.calls == 1:
            return DummyResult(self.display_run)
        if self.calls == 2:
            return DummyResult(self.active_run)
        return DummyResult(None)


def test_status_reports_analyze_model(monkeypatch):
    run = SimpleNamespace(
        id=11,
        started_at=SimpleNamespace(date=lambda: __import__("datetime").date(2026, 3, 24)),
        topics_count=2,
        status="ok",
        errors_json="[]",
    )

    monkeypatch.setattr(api_routes, "AsyncSessionLocal", lambda: DummySession(run, None))
    monkeypatch.setattr(api_routes, "get_wewe_health", lambda _client: asyncio.sleep(0, result={"status": "ok"}))
    monkeypatch.setattr(api_routes, "_display_run_status", lambda _run, _errors: "ok")
    monkeypatch.setattr(api_routes, "ANALYZE_MODEL", "deepseek-chat")
    monkeypatch.setattr(api_routes, "QWEN_API_KEY", "qwen-token")

    result = asyncio.run(api_routes.status(DummyRequest()))

    assert result["modules"]["analyzer"] == "deepseek"
    assert result["config"]["model"] == "deepseek-chat"
