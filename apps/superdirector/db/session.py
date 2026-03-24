import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
from config import SQLITE_PATH
from db.models import Base


def _db_url() -> str:
    return f"sqlite+aiosqlite:///{SQLITE_PATH}"


engine = create_async_engine(_db_url(), future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

_TOPIC_MIGRATIONS = {
    "source": "ALTER TABLE topics ADD COLUMN source TEXT",
    "perf_views": "ALTER TABLE topics ADD COLUMN perf_views INTEGER",
    "perf_likes": "ALTER TABLE topics ADD COLUMN perf_likes INTEGER",
    "perf_collects": "ALTER TABLE topics ADD COLUMN perf_collects INTEGER",
    "publish_match_terms": "ALTER TABLE topics ADD COLUMN publish_match_terms TEXT",
    "topic_line_primary": "ALTER TABLE topics ADD COLUMN topic_line_primary TEXT",
    "topic_line_secondary": "ALTER TABLE topics ADD COLUMN topic_line_secondary TEXT",
    "original_title": "ALTER TABLE topics ADD COLUMN original_title TEXT",
    "localized_title": "ALTER TABLE topics ADD COLUMN localized_title TEXT",
    "line_confidence": "ALTER TABLE topics ADD COLUMN line_confidence FLOAT",
    "content_role": "ALTER TABLE topics ADD COLUMN content_role TEXT",
    "creator_fit": "ALTER TABLE topics ADD COLUMN creator_fit TEXT",
    "li_jie_value": "ALTER TABLE topics ADD COLUMN li_jie_value TEXT",
    "zhang_auntie_value": "ALTER TABLE topics ADD COLUMN zhang_auntie_value TEXT",
    "audience_core": "ALTER TABLE topics ADD COLUMN audience_core TEXT",
    "compliance_risk": "ALTER TABLE topics ADD COLUMN compliance_risk TEXT",
    "actionability_risk": "ALTER TABLE topics ADD COLUMN actionability_risk TEXT",
    "topic_cluster": "ALTER TABLE topics ADD COLUMN topic_cluster TEXT",
    "cluster_mismatch": "ALTER TABLE topics ADD COLUMN cluster_mismatch INTEGER DEFAULT 0",
    "parent_topic_cluster": "ALTER TABLE topics ADD COLUMN parent_topic_cluster TEXT",
    "series_anchor_id": "ALTER TABLE topics ADD COLUMN series_anchor_id TEXT",
    "reject_type": "ALTER TABLE topics ADD COLUMN reject_type TEXT DEFAULT 'none'",
    "rejection_reason": "ALTER TABLE topics ADD COLUMN rejection_reason TEXT",
    "timeliness_window": "ALTER TABLE topics ADD COLUMN timeliness_window TEXT",
    "platform_fit": "ALTER TABLE topics ADD COLUMN platform_fit TEXT",
    "decision_impact_level": "ALTER TABLE topics ADD COLUMN decision_impact_level TEXT",
    "manual_override_note": "ALTER TABLE topics ADD COLUMN manual_override_note TEXT",
    "selection_rank_reason": "ALTER TABLE topics ADD COLUMN selection_rank_reason TEXT",
    "editorial_priority_score": "ALTER TABLE topics ADD COLUMN editorial_priority_score FLOAT",
    "frame_status": "ALTER TABLE topics ADD COLUMN frame_status TEXT",
    "frame_tier": "ALTER TABLE topics ADD COLUMN frame_tier TEXT",
    "frame_rejection_reason": "ALTER TABLE topics ADD COLUMN frame_rejection_reason TEXT",
}

_PIPELINE_RUN_MIGRATIONS = {
    "raw_item_count": "ALTER TABLE pipeline_runs ADD COLUMN raw_item_count INTEGER DEFAULT 0",
}


async def _ensure_topic_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(topics)"))
    existing = {row[1] for row in result.fetchall()}
    for column, ddl in _TOPIC_MIGRATIONS.items():
        if column not in existing:
            await conn.execute(text(ddl))


async def _ensure_pipeline_run_columns(conn) -> None:
    result = await conn.execute(text("PRAGMA table_info(pipeline_runs)"))
    existing = {row[1] for row in result.fetchall()}
    for column, ddl in _PIPELINE_RUN_MIGRATIONS.items():
        if column not in existing:
            await conn.execute(text(ddl))


async def init_db() -> None:
    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_topic_columns(conn)
        await _ensure_pipeline_run_columns(conn)
        await conn.execute(text("PRAGMA journal_mode=WAL"))
