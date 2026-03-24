from __future__ import annotations

import asyncio
from importlib import reload


def test_require_env_allows_direct_network_and_respects_portable_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.setenv("DOUYIN_COOKIE_PATH", str(tmp_path / ".douyin_cookie"))
    monkeypatch.setenv(
        "SUPERDIRECTOR_SERVICE_PATH",
        str(tmp_path / "systemd" / "superdirector.service"),
    )
    monkeypatch.setenv("MEDIA_CRAWLER_DIR", "")

    import core.config as config_module

    reload(config_module)

    config_module.require_env()

    assert config_module.HTTP_PROXY is None
    assert config_module.HTTPS_PROXY is None
    assert config_module.DOUYIN_COOKIE_PATH == str(tmp_path / ".douyin_cookie")
    assert config_module.SUPERDIRECTOR_SERVICE_PATH == str(
        tmp_path / "systemd" / "superdirector.service"
    )
    assert config_module.MEDIA_CRAWLER_ENABLED is False


def test_output_topics_follow_editorial_priority(monkeypatch, tmp_path):
    db_path = tmp_path / "ordering.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    import core.config as config_module
    import db.crud as crud_module
    import db.session as session_module

    reload(config_module)
    reload(session_module)

    async def scenario():
        await session_module.init_db()
        async with session_module.AsyncSessionLocal() as session:
            run = await crud_module.create_pipeline_run(session)
            await crud_module.insert_topics(
                session,
                [
                    {
                        "topic_id": "score-first",
                        "date": "2026-03-24",
                        "title": "总分高但 editorial 低",
                        "score_total": 9.5,
                        "editorial_priority_score": 5.0,
                        "selection_rank_reason": "总分高",
                        "reject_type": "none",
                        "pipeline_run_id": run.id,
                    },
                    {
                        "topic_id": "editorial-first",
                        "date": "2026-03-24",
                        "title": "editorial 更高",
                        "score_total": 8.0,
                        "editorial_priority_score": 9.0,
                        "selection_rank_reason": "editorial 高",
                        "reject_type": "none",
                        "pipeline_run_id": run.id,
                    },
                ],
            )
            output_rows = await crud_module.get_output_topics_for_run(session, run.id, limit=5)
            today_rows = await crud_module.get_today_topics(session, "2026-03-24")
            return output_rows, today_rows

    output_rows, today_rows = asyncio.run(scenario())

    assert output_rows[0].topic_id == "editorial-first"
    assert today_rows[0].topic_id == "editorial-first"
