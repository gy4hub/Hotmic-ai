import asyncio
import os
from tempfile import NamedTemporaryFile

from db import crud
from db.session import AsyncSessionLocal, engine, init_db
from db.models import RawCandidate


async def _setup_db(path: str):
    os.environ['SQLITE_PATH'] = path


def test_raw_candidates_insert_and_consume(monkeypatch, tmp_path):
    db_path = tmp_path / 'raw_candidates.db'
    monkeypatch.setenv('SQLITE_PATH', str(db_path))

    from importlib import reload
    import config
    import db.session as session_module

    reload(config)
    reload(session_module)

    async def scenario():
        await session_module.init_db()
        async with session_module.AsyncSessionLocal() as session:
            run = await crud.create_pipeline_run(session)
            rows = await crud.insert_raw_candidates(
                session,
                run_id=run.id,
                items=[
                    {
                        'title': '题目一',
                        'url': 'https://a/1',
                        'source': 'brave_search',
                        'raw_snippet': '摘要',
                        'timestamp': '2026-03-17',
                        'fingerprint': 'fp1',
                    },
                    {
                        'title': '题目一',
                        'url': 'https://a/1',
                        'source': 'brave_search',
                        'raw_snippet': '摘要',
                        'timestamp': '2026-03-17',
                        'fingerprint': 'fp1',
                    },
                ],
            )
            assert len(rows) == 1
            pending = await crud.list_pending_raw_candidates(session)
            assert len(pending) == 1
            await crud.mark_raw_candidates_consumed(session, [pending[0].id])
            pending_after = await crud.list_pending_raw_candidates(session)
            assert pending_after == []

    asyncio.run(scenario())
