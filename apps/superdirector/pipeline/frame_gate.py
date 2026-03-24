from __future__ import annotations

import json
from typing import Any

from pipeline.editorial import HARD_REJECT_PATTERNS

_HOOK_REDLINE_PATTERNS: dict[str, tuple[str, ...]] = {
    "C01": ("你可能是", "你这是", "根据你说的情况", "大概率就是"),
    "C02": ("一定能", "保证", "绝对有效", "肯定会好", "包治"),
    "C03": ("推荐品牌", "品牌药", "具体型号", "买这个牌子"),
    "C04": ("国家级专家认证", "主任医师亲授", "权威专家背书"),
    "C05": ("研究证明", "100%", "90%的人都"),
    "C06": ("国家规定必须", "医保已经明确要求", "官方已经宣布必须"),
}


def _get_value(topic: Any, key: str) -> Any:
    if isinstance(topic, dict):
        return topic.get(key)
    return getattr(topic, key, None)


def _parse_frame(topic: Any) -> dict[str, Any]:
    frame = _get_value(topic, "frame")
    if isinstance(frame, dict):
        return frame

    raw = _get_value(topic, "frame_json")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _compact_len(text: Any) -> int:
    return len("".join(str(text or "").split()))


def _platform_hook_limit(platform: str | None) -> int:
    normalized = str(platform or "").strip().lower()
    if normalized in {"shipinhao", "wechat_video"}:
        return 30
    return 25


def _contains_any(text: str, patterns: tuple[str, ...]) -> str | None:
    normalized = str(text or "").lower()
    for pattern in patterns:
        if pattern.lower() in normalized:
            return pattern
    return None


def frame_quality_gate(topic: dict | Any) -> tuple[bool, str]:
    """检查 frame JSON 的质量，返回 (通过, 原因)。"""
    frame = _parse_frame(topic)
    if not frame:
        return False, "缺少 frame JSON"

    hook = str(frame.get("hook") or "").strip()
    outline = frame.get("outline") or []
    cta = str(frame.get("cta") or "").strip()
    platform = _get_value(topic, "platform_priority")
    frame_tier = str(_get_value(topic, "frame_tier") or "full").strip().lower()
    is_lite = frame_tier == "lite"

    if not hook:
        return False, "hook 为空"
    hook_limit = _platform_hook_limit(platform)
    if _compact_len(hook) > hook_limit:
        return False, f"hook 过长：{_compact_len(hook)} 字，超过 {hook_limit} 字限制"

    if not isinstance(outline, list):
        return False, "outline 必须是数组"
    min_outline_count = 3 if is_lite else 4
    max_outline_count = 5 if is_lite else 7
    if not min_outline_count <= len(outline) <= max_outline_count:
        return False, f"outline 条数不合规：{len(outline)} 条，要求 {min_outline_count}-{max_outline_count} 条"
    for index, item in enumerate(outline, start=1):
        minimum_outline_len = 6 if is_lite else 8
        if _compact_len(item) < minimum_outline_len:
            return False, f"outline 第 {index} 条过短，至少 {minimum_outline_len} 字"

    if not cta and not is_lite:
        return False, "cta 为空"

    for code, patterns in _HOOK_REDLINE_PATTERNS.items():
        matched = _contains_any(hook, patterns)
        if matched:
            return False, f"hook 命中合规红线 {code}: {matched}"

    matched_hard_reject = _contains_any(hook, HARD_REJECT_PATTERNS)
    if matched_hard_reject:
        return False, f"hook 命中禁区词: {matched_hard_reject}"

    return True, "通过"
