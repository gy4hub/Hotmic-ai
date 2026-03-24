from datetime import datetime
from compat import UTC
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=_utc_now_naive)
    finished_at = Column(DateTime)
    status = Column(String(32), default="running")
    topics_count = Column(Integer, default=0)
    raw_item_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    total_tokens = Column(Integer)
    total_cost_usd = Column(Float)
    errors_json = Column(Text)


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True)
    topic_id = Column(String(64), unique=True, index=True)
    date = Column(String(16))
    title = Column(Text)
    angle_type = Column(String(32))
    platform_priority = Column(String(32))
    content_type = Column(String(32))
    status = Column(String(32), default="ok")

    # Source fields
    url = Column(Text)
    source = Column(String(128))
    timestamp = Column(String(64))
    raw_snippet = Column(Text)

    # Analysis fields
    summary = Column(Text)
    keywords = Column(Text)
    competitor_angle = Column(Text)
    angle_gap = Column(Text)
    topic_line_primary = Column(String(32))
    topic_line_secondary = Column(String(32))
    line_confidence = Column(Float)
    content_role = Column(String(32))
    creator_fit = Column(String(16))
    li_jie_value = Column(String(16))
    zhang_auntie_value = Column(String(16))
    audience_core = Column(String(32))
    compliance_risk = Column(String(16))
    actionability_risk = Column(String(16))
    topic_cluster = Column(String(64))
    parent_topic_cluster = Column(String(64))
    series_anchor_id = Column(String(64))
    reject_type = Column(String(32), default="none")
    rejection_reason = Column(Text)
    timeliness_window = Column(String(32))
    platform_fit = Column(String(32))
    decision_impact_level = Column(String(16))
    manual_override_note = Column(Text)
    selection_rank_reason = Column(Text)
    editorial_priority_score = Column(Float)

    # Scores (Group B)
    score_total = Column(Float)
    score_emotion = Column(Float)
    score_timely = Column(Float)
    score_subvert = Column(Float)
    score_relate = Column(Float)
    score_spread = Column(Float)
    score_tension = Column(Float)
    score_depth = Column(Float)

    # Group C (search)
    search_terms = Column(Text)
    search_queries = Column(Text)
    search_sources = Column(Text)

    # Group D (monetize)
    monetize_goods = Column(Text)
    monetize_course = Column(Text)
    monetize_notes = Column(Text)

    # Group E (creator ops)
    creator_ops = Column(Text)
    creator_notes = Column(Text)
    publish_match_terms = Column(Text)
    review_status = Column(String(32))

    # Group F (post-publish data)
    publish_status = Column(String(32))
    publish_url = Column(Text)
    publish_at = Column(String(64))
    perf_views = Column(Integer)
    perf_likes = Column(Integer)
    perf_collects = Column(Integer)
    perf_watch_rate = Column(Float)
    perf_favorite_rate = Column(Float)
    perf_comments = Column(Integer)
    perf_shares = Column(Integer)

    # Group G (system metadata)
    pipeline_run_id = Column(Integer, ForeignKey("pipeline_runs.id"))
    model_version = Column(String(64))
    created_at = Column(DateTime, default=_utc_now_naive)
    updated_at = Column(DateTime, default=_utc_now_naive)

    errors_json = Column(Text)
    frame_json = Column(Text)
    frame_status = Column(String(32))
    frame_rejection_reason = Column(Text)


class ScoreDetail(Base):
    __tablename__ = "score_details"

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"))
    dimension = Column(String(32))
    raw_score = Column(Float)
    weighted_score = Column(Float)
    platform = Column(String(32))
    weight_version = Column(String(32))


class ApiCostLog(Base):
    __tablename__ = "api_cost_log"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=_utc_now_naive)
    provider = Column(String(32))
    model = Column(String(64))
    endpoint = Column(Text)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    cost_usd = Column(Float)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=_utc_now_naive)
    level = Column(String(16))
    module = Column(String(64))
    message = Column(Text)
    details_json = Column(Text)


class BitableSyncTask(Base):
    __tablename__ = "bitable_sync_tasks"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(32), nullable=False)
    entity_key = Column(String(128), nullable=False, index=True)
    table_name = Column(String(32), nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    error_message = Column(Text)
    last_attempted_at = Column(DateTime)
    created_at = Column(DateTime, default=_utc_now_naive)
    updated_at = Column(DateTime, default=_utc_now_naive)


class ScheduleJob(Base):
    __tablename__ = "schedule_jobs"

    job_id = Column(String(64), primary_key=True)
    cron_hour = Column(Integer, nullable=False)
    cron_minute = Column(Integer, nullable=False)
    enabled = Column(Integer, default=1, nullable=False)
    description = Column(Text)
    last_run_at = Column(String(64))
    last_run_status = Column(String(32))
    last_run_error = Column(Text)
    updated_at = Column(String(64))


class PlatformFeedback(Base):
    __tablename__ = "platform_feedback"

    id = Column(Integer, primary_key=True)
    topic_id = Column(String(64), index=True, nullable=False)
    platform = Column(String(32), nullable=False)
    video_id = Column(String(64))
    publish_url = Column(Text, nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    play_count = Column(Integer)
    digg_count = Column(Integer)
    comment_count = Column(Integer)
    collect_count = Column(Integer)
    share_count = Column(Integer)
    completion_rate = Column(Float)
    raw_json = Column(Text)
    error_message = Column(Text)
    collected_at = Column(DateTime, default=_utc_now_naive)
    updated_at = Column(DateTime, default=_utc_now_naive)


class RawCandidate(Base):
    __tablename__ = "raw_candidates"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("pipeline_runs.id"), nullable=False, index=True)
    source = Column(String(128))
    title = Column(Text)
    url = Column(Text)
    snippet = Column(Text)
    published_at = Column(String(64))
    collected_at = Column(DateTime, default=_utc_now_naive)
    fingerprint = Column(String(128), index=True)
    status = Column(String(32), default="pending", nullable=False)
