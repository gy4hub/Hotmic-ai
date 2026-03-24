from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import main


class DummyClient:
    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs

    async def aclose(self):
        return None


class DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_lifespan_skips_scheduler_when_disabled(monkeypatch):
    called = {"scheduler": False}

    monkeypatch.setattr(main, "SCHEDULER_ENABLED", False)
    monkeypatch.setattr(main, "require_env", lambda: None)
    monkeypatch.setattr(main, "init_db", lambda: asyncio.sleep(0))
    monkeypatch.setattr(main, "flush_bitable_outbox", lambda _client: asyncio.sleep(0, result={"synced": 0, "failed": 0}))
    monkeypatch.setattr(main, "stop_scheduler", lambda: None)
    monkeypatch.setattr(main.httpx, "AsyncClient", DummyClient)

    async def fake_start_scheduler(_app_state):
        called["scheduler"] = True
        return object()

    monkeypatch.setattr(main, "start_scheduler", fake_start_scheduler)

    async def exercise():
        async with main.lifespan(main.app):
            assert hasattr(main.app.state, "ext_client")

    asyncio.run(exercise())

    assert called["scheduler"] is False


def test_lifespan_logs_scheduler_start_failure_without_crashing(monkeypatch):
    logged = []

    monkeypatch.setattr(main, "SCHEDULER_ENABLED", True)
    monkeypatch.setattr(main, "require_env", lambda: None)
    monkeypatch.setattr(main, "init_db", lambda: asyncio.sleep(0))
    monkeypatch.setattr(main, "flush_bitable_outbox", lambda _client: asyncio.sleep(0, result={"synced": 0, "failed": 0}))
    monkeypatch.setattr(main, "stop_scheduler", lambda: None)
    monkeypatch.setattr(main.httpx, "AsyncClient", DummyClient)
    monkeypatch.setattr(main, "AsyncSessionLocal", lambda: DummySession())

    async def fake_start_scheduler(_app_state):
        raise RuntimeError("scheduler boom")

    async def fake_log_system(_session, *, level, module, message, details):
        logged.append(
            {
                "level": level,
                "module": module,
                "message": message,
                "details": details,
            }
        )

    monkeypatch.setattr(main, "start_scheduler", fake_start_scheduler)
    monkeypatch.setattr(main.crud, "log_system", fake_log_system)

    async def exercise():
        async with main.lifespan(main.app):
            assert hasattr(main.app.state, "int_client")

    asyncio.run(exercise())

    assert logged[0]["module"] == "scheduler"
    assert logged[0]["level"] == "error"
    assert "scheduler boom" in logged[0]["details"]["error"]
