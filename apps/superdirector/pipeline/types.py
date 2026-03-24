from __future__ import annotations

from typing import Any, TypedDict


class FramePayload(TypedDict, total=False):
    hook: str
    outline: list[str]
    cta: str
    monetize_hook: str
    platform_tips: str


class TopicPayload(TypedDict, total=False):
    topic_id: str
    id: int
    date: str
    title: str
    original_title: str
    localized_title: str
    source: str
    source_type: str
    evergreen_id: str
    timestamp: str
    raw_snippet: str
    summary: str
    keywords: list[str] | str
    url: str
    status: str
    errors: list[str]
    score_total: float
    editorial_priority_score: float
    topic_line_primary: str
    content_role: str
    topic_cluster: str
    cluster_mismatch: bool
    platform_priority: str
    publish_status: str
    publish_at: str
    publish_url: str
    perf_watch_rate: float
    frame_status: str
    frame_tier: str
    frame_rejection_reason: str | None
    frame: FramePayload | dict[str, Any]
    pipeline_run_id: int
    model_version: str


class ScoreDetailPayload(TypedDict, total=False):
    topic_id: str | int
    dimension: str
    raw_score: float
    weighted_score: float
    platform: str
    weight_version: str


class UsageSummary(TypedDict, total=False):
    provider: str
    model: str
    endpoint: str
    input_tokens: int
    output_tokens: int


class EditorialMeta(TypedDict, total=False):
    mode: str
    line_distribution: dict[str, int]
    role_distribution: dict[str, int]
