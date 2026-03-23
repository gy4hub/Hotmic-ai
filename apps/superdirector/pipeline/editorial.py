from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
import json
from pathlib import Path
from typing import Any

from config import (
    EDITORIAL_FATIGUE_PENALTY_STEP,
    EDITORIAL_HINTS_PATH,
    EDITORIAL_FATIGUE_WINDOW_DAYS,
    EDITORIAL_HIGH_RISK_PENALTY,
    EDITORIAL_MEDIUM_RISK_PENALTY,
    EDITORIAL_PHASE,
    EDITORIAL_RECENT_WINDOW_DAYS,
    EDITORIAL_ROLE_BASELINE_THRESHOLD,
    EDITORIAL_SOURCE_CONCENTRATION_PENALTY,
    EDITORIAL_TARGET_MIX_DEFAULT,
    EDITORIAL_TARGET_ROLE_MIX_DEFAULT,
    TOP_N,
    load_casey_profile,
    load_topic_clusters,
)

PRIMARY_LINES = {"public_issue", "family_anxiety", "consumer_scam", "rejected"}
CONTENT_ROLES = {"spread", "save", "followup"}
CREATOR_FITS = {"strong", "medium", "weak"}
LI_JIE_VALUES = {"click", "save", "ignore"}
ZHANG_AUNTIE_VALUES = {"forward", "watch", "ignore"}
AUDIENCE_CORES = {
    "family_decision_maker",
    "child_parent",
    "elder_parent",
    "health_consumer",
    "patient_family",
    "industry_insider",
    "general_public",
}
RISK_LEVELS = {"low", "medium", "high"}
REJECT_TYPES = {"none", "quarantine", "hard_reject"}
TIMELINESS_WINDOWS = {"burst", "slow_burn", "evergreen"}
PLATFORM_FITS = {"douyin", "shipinhao", "both"}
IMPACT_LEVELS = {"low", "medium", "high"}
INTERNATIONAL_SOURCES = {
    "who_alerts",
    "stat_pharma",
    "rss_stat_backup",
    "rss_nyt_health",
    "rss_sciencedaily_health",
    "fda_safety",
}


@lru_cache(maxsize=1)
def _editorial_hints_config() -> dict[str, list[str]]:
    path = Path(EDITORIAL_HINTS_PATH)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid editorial hints config: {path}")
    return {
        str(key): [str(item) for item in value]
        for key, value in data.items()
        if isinstance(value, list)
    }


def _hint_tuple(name: str) -> tuple[str, ...]:
    values = _editorial_hints_config().get(name)
    if values is None:
        raise RuntimeError(f"Missing editorial hints config key: {name}")
    return tuple(values)


def _hint_set(name: str) -> set[str]:
    return set(_hint_tuple(name))


HARD_REJECT_PATTERNS = _hint_tuple("hard_reject_patterns")
QUARANTINE_PATTERNS = _hint_tuple("quarantine_patterns")
PUBLIC_ISSUE_HINTS = _hint_tuple("public_issue_hints")
FAMILY_ANXIETY_HINTS = _hint_tuple("family_anxiety_hints")
CONSUMER_SCAM_HINTS = _hint_tuple("consumer_scam_hints")
SPREAD_HINTS = _hint_tuple("spread_hints")
SAVE_HINTS = _hint_tuple("save_hints")
FOLLOWUP_HINTS = _hint_tuple("followup_hints")
CHILD_PARENT_HINTS = _hint_tuple("child_parent_hints")
ELDER_PARENT_HINTS = _hint_tuple("elder_parent_hints")
PATIENT_FAMILY_HINTS = _hint_tuple("patient_family_hints")
INDUSTRY_HINTS = _hint_tuple("industry_hints")
HIGH_COMPLIANCE_HINTS = _hint_tuple("high_compliance_hints")
HIGH_ACTIONABILITY_HINTS = _hint_tuple("high_actionability_hints")
MEDICAL_ADVICE_TITLE_HINTS = _hint_tuple("medical_advice_title_hints")
MEDICAL_ADVICE_BODY_HINTS = _hint_tuple("medical_advice_body_hints")
MEDIUM_RISK_HINTS = _hint_tuple("medium_risk_hints")
OFFICIAL_STYLE_SOURCES = _hint_set("official_style_sources")
DOMESTIC_RELEVANCE_HINTS = _hint_tuple("domestic_relevance_hints")
LOCAL_FAMILY_SHARE_HINTS = _hint_tuple("local_family_share_hints")
FOREIGN_CONTEXT_HINTS = _hint_tuple("foreign_context_hints")
OFFTOPIC_TITLE_HINTS = _hint_tuple("offtopic_title_hints")
MEDICAL_CORE_HINTS = _hint_tuple("medical_core_hints")
POLICY_TRANSLATION_HINTS = _hint_tuple("policy_translation_hints")
HOUSEHOLD_PAIN_HINTS = _hint_tuple("household_pain_hints")
CREATOR_STRONG_HINTS = _hint_tuple("creator_strong_hints")
CREATOR_WEAK_HINTS = _hint_tuple("creator_weak_hints")
ZHANG_FORWARD_HINTS = _hint_tuple("zhang_forward_hints")
NARROW_SPECIALTY_HINTS = _hint_tuple("narrow_specialty_hints")
HEALTH_PANIC_TITLE_HINTS = _hint_tuple("health_panic_title_hints")


@dataclass(slots=True)
class EditorialCandidate:
    item: dict[str, Any]
    quality_score: float
    line_gap_bonus: float
    role_gap_bonus: float
    performance_feedback_bonus: float
    creator_fit_bonus: float
    li_jie_bonus: float
    zhang_auntie_bonus: float
    fatigue_penalty: float
    source_concentration_penalty: float
    risk_penalty: float
    domestic_relevance_penalty: float
    local_shareability_bonus: float
    editorial_priority_score: float
    selection_rank_reason: str


def _as_text(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts if part).strip()


def _normalize(text: str | None) -> str:
    return " ".join((text or "").strip().lower().split())


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    normalized = _normalize(text)
    return any(pattern.lower() in normalized for pattern in patterns)


@lru_cache(maxsize=1)
def _cluster_map() -> tuple[dict[str, str], list[str]]:
    alias_to_label: dict[str, str] = {}
    labels: list[str] = []
    for entry in load_topic_clusters():
        label = str(entry.get("label") or "").strip() or "unknown_cluster"
        labels.append(label)
        alias_to_label[_normalize(label)] = label
        for alias in entry.get("aliases") or []:
            alias_to_label[_normalize(str(alias))] = label
    if "unknown_cluster" not in labels:
        labels.append("unknown_cluster")
        alias_to_label["unknown_cluster"] = "unknown_cluster"
    return alias_to_label, labels


def allowed_clusters() -> list[str]:
    return list(_cluster_map()[1])


def editorial_config_summary() -> dict[str, Any]:
    return {
        "phase": EDITORIAL_PHASE,
        "phase_meaning": {
            1: "shadow",
            2: "editorial_selection",
            3: "editorial_selection_with_fatigue",
        }.get(EDITORIAL_PHASE, "custom"),
        "target_mix_default": EDITORIAL_TARGET_MIX_DEFAULT,
        "target_role_mix_default": EDITORIAL_TARGET_ROLE_MIX_DEFAULT,
        "role_baseline_threshold": EDITORIAL_ROLE_BASELINE_THRESHOLD,
        "controlled_clusters": allowed_clusters(),
        "high_risk_policy": "manual_override_required",
    }


def build_editorial_prompt_section() -> str:
    profile = load_casey_profile()
    creator_name = str(
        profile.get("display_name")
        or ((profile.get("positioning") or {}).get("identity"))
        or "创作者"
    ).strip()
    decision_layer = (profile.get("dual_audience_model") or {}).get("decision_layer") or {}
    spread_layer = (profile.get("dual_audience_model") or {}).get("spread_layer") or {}
    decision_label = str(decision_layer.get("label") or "李姐").strip()
    decision_who = str(decision_layer.get("who") or "家庭健康决策者").strip()
    decision_action = str(decision_layer.get("expected_action") or "点开/收藏").strip()
    spread_label = str(spread_layer.get("label") or "张阿姨").strip()
    spread_who = str(spread_layer.get("who") or "家族群传播层受众").strip()
    spread_action = str(spread_layer.get("expected_action") or "转发到家族群").strip()
    clusters = " / ".join(cluster for cluster in allowed_clusters() if cluster != "unknown_cluster")
    return (
        "\n\n【新增总编字段】\n"
        "请在每个对象中额外输出这些字段：\n"
        "- topic_line_primary: public_issue | family_anxiety | consumer_scam | rejected\n"
        "- topic_line_secondary: public_issue | family_anxiety | consumer_scam | rejected | null\n"
        "- line_confidence: 0 到 1\n"
        "- content_role: spread | save | followup\n"
        "- creator_fit: strong | medium | weak\n"
        "- li_jie_value: click | save | ignore\n"
        "- zhang_auntie_value: forward | watch | ignore\n"
        "- audience_core: family_decision_maker | child_parent | elder_parent | health_consumer | patient_family | industry_insider | general_public\n"
        "- compliance_risk: low | medium | high\n"
        "- actionability_risk: low | medium | high\n"
        f"- topic_cluster: 只能从这个受控词表中选择：{clusters}；若无法匹配，请输出 unknown_cluster\n"
        "- reject_type: none | quarantine | hard_reject\n"
        "- rejection_reason: 若 reject_type 不是 none，说明原因；否则可为空\n"
        "- timeliness_window: burst | slow_burn | evergreen\n"
        "- platform_fit: douyin | shipinhao | both\n"
        "- decision_impact_level: low | medium | high\n"
        "- parent_topic_cluster: 若 content_role 是 followup，请给出对应的父 cluster；否则可为空\n"
        "- series_anchor_id: 若 content_role 是 followup 且存在明确锚点，可填写；否则可为空\n"
        "\n受众参考：\n"
        f"- 决策层：{decision_label}（{decision_who}）\n"
        f"- 传播层：{spread_label}（{spread_who}）\n"
        "\n规则：\n"
        "1. 先判断是否属于禁区，再判断 reject_type。\n"
        "2. 再判断主线主次标签、content_role、risk 和 cluster。\n"
        "3. high risk 题可以保留，但不要偷改成 medium。\n"
        f"4. creator_fit 要判断这题{creator_name}能不能用政策、定价、供应链、质量标准、消费决策的视角讲清。\n"
        f"5. 传播款必须同时考虑：{decision_label}会不会{decision_action}，{spread_label}会不会{spread_action}。\n"
        "6. 不允许自己发明新的 topic_cluster 名称。\n"
        "7. 如果没有有效 parent_topic_cluster 或 series_anchor_id，不要输出 followup；改成 save。\n"
    )


def _coerce_enum(value: Any, allowed: set[str], default: str) -> str:
    candidate = _normalize(str(value or ""))
    for option in allowed:
        if candidate == option:
            return option
    return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return round(number, 3)


def _enum_order(value: str, ordered: tuple[str, ...], fallback: str) -> int:
    try:
        return ordered.index(value)
    except ValueError:
        return ordered.index(fallback)


def _cap_down_enum(value: str, inferred: str, ordered: tuple[str, ...], fallback: str) -> str:
    value_idx = _enum_order(value, ordered, fallback)
    inferred_idx = _enum_order(inferred, ordered, fallback)
    return ordered[min(value_idx, inferred_idx)]


def _canonical_cluster(value: Any, text: str) -> str:
    alias_to_label, labels = _cluster_map()
    candidate = _normalize(str(value or ""))
    if candidate in alias_to_label:
        return alias_to_label[candidate]
    normalized_text = _normalize(text)
    for alias, label in alias_to_label.items():
        if alias and alias != "unknown_cluster" and alias in normalized_text:
            return label
    return "unknown_cluster" if "unknown_cluster" in labels else labels[0]


def _infer_reject_type(text: str, title_text: str = "") -> tuple[str, str]:
    normalized_title = _normalize(title_text)
    if any(token in normalized_title for token in OFFTOPIC_TITLE_HINTS) and not any(
        token in normalized_title for token in MEDICAL_CORE_HINTS
    ):
        return "hard_reject", "标题主体偏离医疗健康主号定位。"
    if any(token in normalized_title for token in MEDICAL_ADVICE_TITLE_HINTS):
        return "quarantine", "表达过于接近具体用药/治疗建议，先隔离，不进主号 Top 5。"
    if any(token in normalized_title for token in HEALTH_PANIC_TITLE_HINTS):
        return "quarantine", "更像情绪型养生恐吓标题，先隔离，不进主号 Top 5。"
    if _contains_any(text, HARD_REJECT_PATTERNS):
        return "hard_reject", "内容偏离主号医疗健康定位。"
    if _contains_any(text, QUARANTINE_PATTERNS):
        return "quarantine", "更像行业素材，先保留观察，不进主号 Top 3。"
    return "none", ""


def _infer_topic_line(text: str, source: str, cluster: str) -> tuple[str, str | None, float]:
    normalized_text = _normalize(text)
    public_hits = sum(keyword in normalized_text for keyword in (hint.lower() for hint in PUBLIC_ISSUE_HINTS))
    family_hits = sum(keyword in normalized_text for keyword in (hint.lower() for hint in FAMILY_ANXIETY_HINTS))
    scam_hits = sum(keyword in normalized_text for keyword in (hint.lower() for hint in CONSUMER_SCAM_HINTS))
    if source in OFFICIAL_STYLE_SOURCES:
        public_hits += 1
    cluster_text = _normalize(cluster)
    if "家庭" in cluster or "儿童" in cluster or "老人" in cluster:
        family_hits += 1
    if "骗局" in cluster or "灰市" in cluster or "网红" in cluster or "医美" in cluster:
        scam_hits += 1
    if "医保" in cluster or "政策" in cluster or "监管" in cluster or "药价" in cluster:
        public_hits += 1
    if any(token in normalized_text for token in ("儿童", "孩子", "家长", "老人", "父母", "长辈", "孙子", "孙女")):
        family_hits += 2
    if any(token in normalized_text for token in ("药盒", "药箱", "批号", "自查", "核对")):
        family_hits += 1
    if cluster in {"假药 / 劣药", "儿童用药", "老年人健康风险", "家庭药箱", "家庭医疗误区"}:
        family_hits += 1
    if cluster == "假药 / 劣药" and any(token in normalized_text for token in ("儿童", "孩子", "家长", "老人", "父母", "药盒", "批号")):
        family_hits += 2

    scores = [
        ("public_issue", public_hits),
        ("family_anxiety", family_hits),
        ("consumer_scam", scam_hits),
    ]
    scores.sort(key=lambda item: item[1], reverse=True)
    primary, primary_score = scores[0]
    secondary = scores[1][0] if scores[1][1] > 0 else None
    if primary_score <= 0:
        return "rejected", None, 0.2
    confidence = min(1.0, 0.45 + 0.12 * primary_score)
    return primary, secondary, round(confidence, 3)


def _infer_content_role(text: str, parent_topic_cluster: str | None, series_anchor_id: str | None) -> str:
    normalized = _normalize(text)
    if any(keyword.lower() in normalized for keyword in FOLLOWUP_HINTS):
        if parent_topic_cluster or series_anchor_id:
            return "followup"
        return "save"
    if (
        any(keyword.lower() in normalized for keyword in SAVE_HINTS)
        or "为什么" in normalized
        or "不等于" in normalized
        or "分几步" in normalized
        or "几道门" in normalized
    ):
        return "save"
    if any(keyword.lower() in normalized for keyword in SPREAD_HINTS):
        return "spread"
    return "spread"


def _infer_audience(text: str, cluster: str) -> str:
    normalized = _normalize(_as_text(text, cluster))
    if any(keyword.lower() in normalized for keyword in CHILD_PARENT_HINTS):
        return "child_parent"
    if any(keyword.lower() in normalized for keyword in ELDER_PARENT_HINTS):
        return "elder_parent"
    if any(keyword.lower() in normalized for keyword in PATIENT_FAMILY_HINTS):
        return "patient_family"
    if any(keyword.lower() in normalized for keyword in INDUSTRY_HINTS):
        return "industry_insider"
    if "骗局" in cluster or "网红" in cluster or "抗衰" in cluster:
        return "health_consumer"
    if "家庭" in cluster or "医保" in normalized:
        return "family_decision_maker"
    return "general_public"


def _infer_creator_fit(
    text: str,
    *,
    line: str,
    source: str,
    cluster: str,
    policy_translation_penalty: float,
) -> str:
    normalized = _normalize(_as_text(text, cluster))
    strong_hits = sum(keyword.lower() in normalized for keyword in CREATOR_STRONG_HINTS)
    weak_hits = sum(keyword.lower() in normalized for keyword in CREATOR_WEAK_HINTS)
    narrow_specialty = any(keyword.lower() in normalized for keyword in NARROW_SPECIALTY_HINTS)
    broad_household = any(token.lower() in normalized for token in HOUSEHOLD_PAIN_HINTS)
    if line == "rejected":
        return "weak"
    if source in INTERNATIONAL_SOURCES and not any(
        token.lower() in normalized for token in DOMESTIC_RELEVANCE_HINTS
    ):
        weak_hits += 1
    if policy_translation_penalty >= 0.22:
        weak_hits += 1
    if strong_hits >= 2 or any(
        token in normalized for token in ("开不出来", "用不上", "315", "外泌体", "私域", "保健品")
    ):
        return "strong"
    if narrow_specialty and not broad_household:
        return "medium"
    if weak_hits >= 2 and strong_hits == 0:
        return "weak"
    if line in {"family_anxiety", "consumer_scam"}:
        return "strong" if strong_hits >= 1 else "medium"
    return "medium"


def _infer_li_jie_value(
    text: str,
    *,
    line: str,
    role: str,
    creator_fit: str,
    decision_impact: str,
) -> str:
    normalized = _normalize(text)
    narrow_specialty = any(keyword.lower() in normalized for keyword in NARROW_SPECIALTY_HINTS)
    if creator_fit == "weak":
        return "ignore"
    if narrow_specialty and decision_impact != "high":
        return "click"
    if role in {"save", "followup"} and (
        decision_impact == "high"
        or any(token in normalized for token in ("孩子", "老人", "爸妈", "保健品", "外泌体", "医保", "药盒"))
    ):
        return "save"
    if line in {"family_anxiety", "consumer_scam"}:
        return "save" if any(token in normalized for token in ("避坑", "为什么", "别再", "误区")) else "click"
    if line == "public_issue":
        if any(token in normalized for token in ("开不出来", "用不上", "药价", "报销", "自费")):
            return "save"
        return "click"
    return "ignore"


def _infer_zhang_auntie_value(
    text: str,
    *,
    line: str,
    creator_fit: str,
    source: str,
) -> str:
    normalized = _normalize(text)
    narrow_specialty = any(keyword.lower() in normalized for keyword in NARROW_SPECIALTY_HINTS)
    has_domestic_anchor = any(token.lower() in normalized for token in DOMESTIC_RELEVANCE_HINTS)
    if creator_fit == "weak":
        return "ignore"
    if source in INTERNATIONAL_SOURCES and not has_domestic_anchor:
        return "ignore"
    if narrow_specialty and not any(token.lower() in normalized for token in ZHANG_FORWARD_HINTS):
        return "watch"
    if any(token.lower() in normalized for token in ZHANG_FORWARD_HINTS) or any(
        token.lower() in normalized for token in LOCAL_FAMILY_SHARE_HINTS
    ):
        return "forward"
    if source in INTERNATIONAL_SOURCES and not any(
        token.lower() in normalized for token in DOMESTIC_RELEVANCE_HINTS
    ):
        return "ignore"
    if line in {"family_anxiety", "consumer_scam"}:
        return "watch"
    if line == "public_issue" and any(token in normalized for token in ("医保", "报销", "药价", "医院")):
        return "watch"
    return "ignore"


def _infer_risk(text: str) -> tuple[str, str]:
    normalized = _normalize(text)
    compliance = "low"
    actionability = "low"
    if any(keyword.lower() in normalized for keyword in MEDIUM_RISK_HINTS):
        compliance = "medium"
        actionability = "medium"
    if any(keyword.lower() in normalized for keyword in HIGH_COMPLIANCE_HINTS):
        compliance = "high"
    if any(keyword.lower() in normalized for keyword in HIGH_ACTIONABILITY_HINTS):
        actionability = "high"
    if any(keyword.lower() in normalized for keyword in MEDICAL_ADVICE_TITLE_HINTS) or any(
        keyword.lower() in normalized for keyword in MEDICAL_ADVICE_BODY_HINTS
    ):
        compliance = "high"
        actionability = "high"
    return compliance, actionability


def _infer_timeliness(text: str, source: str) -> str:
    normalized = _normalize(text)
    if source in OFFICIAL_STYLE_SOURCES or "最新" in normalized or "曝光" in normalized or "警报" in normalized:
        return "burst"
    if "指南" in normalized or "误区" in normalized or "清单" in normalized:
        return "evergreen"
    return "slow_burn"


def _infer_platform_fit(line: str, role: str) -> str:
    if role == "spread":
        return "douyin"
    if line == "family_anxiety":
        return "shipinhao"
    return "both"


def _infer_decision_impact(cluster: str, line: str, audience_core: str) -> str:
    if audience_core in {"family_decision_maker", "patient_family"}:
        return "high"
    if line == "public_issue" or "医保" in cluster or "用药" in cluster:
        return "high"
    if line == "consumer_scam":
        return "medium"
    return "medium"


def is_official_press_style(topic: dict[str, Any]) -> bool:
    source = str(topic.get("source") or "")
    title = _normalize(str(topic.get("title") or ""))
    if source not in OFFICIAL_STYLE_SOURCES:
        return False
    return any(
        marker in title
        for marker in ("meets with", "notice", "commissioner", "regulation", "通报", "会见", "召开", "发布")
    )


def normalize_editorial_item(topic: dict[str, Any], item: dict[str, Any] | None) -> dict[str, Any]:
    item = item or {}
    title_text = str(item.get("localized_title") or topic.get("title") or "")
    raw_snippet = str(topic.get("raw_snippet") or "")
    keywords_text = " ".join(item.get("keywords") or [])
    base_text = _as_text(
        title_text,
        item.get("summary"),
        keywords_text,
        raw_snippet,
    )
    evidence_text = _as_text(title_text, keywords_text, raw_snippet)

    reject_type = _coerce_enum(item.get("reject_type"), REJECT_TYPES, "none")
    rejection_reason = str(item.get("rejection_reason") or "").strip()
    inferred_reject_type, inferred_reason = _infer_reject_type(
        base_text,
        title_text,
    )
    if reject_type == "none" and inferred_reject_type != "none":
        reject_type = inferred_reject_type
        rejection_reason = rejection_reason or inferred_reason

    cluster = _canonical_cluster(item.get("topic_cluster"), base_text)
    primary = _coerce_enum(item.get("topic_line_primary"), PRIMARY_LINES, "")
    secondary_raw = str(item.get("topic_line_secondary") or "").strip()
    secondary = _coerce_enum(secondary_raw, PRIMARY_LINES, "") if secondary_raw else ""
    confidence = _coerce_float(item.get("line_confidence"), 0.0)

    inferred_primary, inferred_secondary, inferred_confidence = _infer_topic_line(base_text, str(topic.get("source") or ""), cluster)
    if not primary or (primary == "rejected" and reject_type == "none"):
        primary = inferred_primary
    if not secondary:
        secondary = inferred_secondary or ""
    if confidence <= 0:
        confidence = inferred_confidence

    parent_topic_cluster = str(item.get("parent_topic_cluster") or "").strip()
    if parent_topic_cluster:
        parent_topic_cluster = _canonical_cluster(parent_topic_cluster, parent_topic_cluster)
        if parent_topic_cluster == "unknown_cluster":
            parent_topic_cluster = ""
    series_anchor_id = str(item.get("series_anchor_id") or "").strip()
    role = _coerce_enum(item.get("content_role"), CONTENT_ROLES, "")
    if not role:
        role = _infer_content_role(base_text, parent_topic_cluster, series_anchor_id)
    if role == "followup" and not (parent_topic_cluster or series_anchor_id):
        role = "save"

    audience = _coerce_enum(item.get("audience_core"), AUDIENCE_CORES, "")
    if not audience:
        audience = _infer_audience(base_text, cluster)

    compliance_risk = _coerce_enum(item.get("compliance_risk"), RISK_LEVELS, "")
    actionability_risk = _coerce_enum(item.get("actionability_risk"), RISK_LEVELS, "")
    inferred_compliance, inferred_actionability = _infer_risk(base_text)
    if not compliance_risk:
        compliance_risk = inferred_compliance
    if not actionability_risk:
        actionability_risk = inferred_actionability
    if inferred_compliance == "high":
        compliance_risk = "high"
    elif inferred_compliance == "medium" and compliance_risk == "low":
        compliance_risk = "medium"
    if inferred_actionability == "high":
        actionability_risk = "high"
    elif inferred_actionability == "medium" and actionability_risk == "low":
        actionability_risk = "medium"

    timeliness_window = _coerce_enum(item.get("timeliness_window"), TIMELINESS_WINDOWS, "")
    if not timeliness_window:
        timeliness_window = _infer_timeliness(base_text, str(topic.get("source") or ""))
    platform_fit = _coerce_enum(item.get("platform_fit"), PLATFORM_FITS, "")
    if not platform_fit:
        platform_fit = _infer_platform_fit(primary, role)
    decision_impact = _coerce_enum(item.get("decision_impact_level"), IMPACT_LEVELS, "")
    if not decision_impact:
        decision_impact = _infer_decision_impact(cluster, primary, audience)

    preview_topic = {
        "title": title_text,
        "summary": item.get("summary"),
        "keywords": item.get("keywords") or [],
        "topic_cluster": cluster,
        "topic_line_primary": primary,
    }
    policy_translation_penalty = _policy_translation_penalty(preview_topic)
    inferred_creator_fit = _infer_creator_fit(
        evidence_text,
        line=primary,
        source=str(topic.get("source") or ""),
        cluster=cluster,
        policy_translation_penalty=policy_translation_penalty,
    )
    creator_fit = _coerce_enum(item.get("creator_fit"), CREATOR_FITS, "")
    if not creator_fit:
        creator_fit = inferred_creator_fit
    else:
        creator_fit = _cap_down_enum(creator_fit, inferred_creator_fit, ("weak", "medium", "strong"), "medium")
    inferred_li_jie_value = _infer_li_jie_value(
        evidence_text,
        line=primary,
        role=role,
        creator_fit=creator_fit,
        decision_impact=decision_impact,
    )
    li_jie_value = _coerce_enum(item.get("li_jie_value"), LI_JIE_VALUES, "")
    if not li_jie_value:
        li_jie_value = inferred_li_jie_value
    else:
        li_jie_value = _cap_down_enum(li_jie_value, inferred_li_jie_value, ("ignore", "click", "save"), "click")
    inferred_zhang_auntie_value = _infer_zhang_auntie_value(
        evidence_text,
        line=primary,
        creator_fit=creator_fit,
        source=str(topic.get("source") or ""),
    )
    zhang_auntie_value = _coerce_enum(item.get("zhang_auntie_value"), ZHANG_AUNTIE_VALUES, "")
    if not zhang_auntie_value:
        zhang_auntie_value = inferred_zhang_auntie_value
    else:
        zhang_auntie_value = _cap_down_enum(
            zhang_auntie_value,
            inferred_zhang_auntie_value,
            ("ignore", "watch", "forward"),
            "watch",
        )

    if reject_type != "none":
        primary = "rejected"
        secondary = ""
        confidence = max(confidence, 0.8)
        creator_fit = "weak"
        li_jie_value = "ignore"
        zhang_auntie_value = "ignore"

    return {
        "topic_line_primary": primary,
        "topic_line_secondary": secondary or None,
        "line_confidence": confidence,
        "content_role": role,
        "creator_fit": creator_fit,
        "li_jie_value": li_jie_value,
        "zhang_auntie_value": zhang_auntie_value,
        "audience_core": audience,
        "compliance_risk": compliance_risk or "low",
        "actionability_risk": actionability_risk or "low",
        "topic_cluster": cluster,
        "reject_type": reject_type,
        "rejection_reason": rejection_reason or None,
        "timeliness_window": timeliness_window or "slow_burn",
        "platform_fit": platform_fit or "both",
        "decision_impact_level": decision_impact or "medium",
        "parent_topic_cluster": parent_topic_cluster or None,
        "series_anchor_id": series_anchor_id or None,
    }


def _recent_mix(topics: list[dict[str, Any]], field: str) -> Counter:
    values = [str(topic.get(field) or "").strip() for topic in topics if topic.get(field)]
    return Counter(values)


def _line_gap_bonus(line: str, recent_topics: list[dict[str, Any]]) -> float:
    counts = _recent_mix(recent_topics, "topic_line_primary")
    total = sum(counts.values())
    target = EDITORIAL_TARGET_MIX_DEFAULT.get(line, 0.0)
    if total <= 0:
        return round(target * 0.8, 4)
    actual = counts.get(line, 0) / total
    gap = target - actual
    return round(max(gap, 0.0) * 1.2, 4)


def _role_gap_bonus(role: str, recent_topics: list[dict[str, Any]], quality_score: float) -> float:
    if quality_score < EDITORIAL_ROLE_BASELINE_THRESHOLD:
        return 0.0
    counts = _recent_mix(recent_topics, "content_role")
    total = sum(counts.values())
    target = EDITORIAL_TARGET_ROLE_MIX_DEFAULT.get(role, 0.0)
    if total <= 0:
        return round(target * 0.8, 4)
    actual = counts.get(role, 0) / total
    gap = target - actual
    return round(max(gap, 0.0) * 0.9, 4)


def _fatigue_penalty(cluster: str, recent_topics: list[dict[str, Any]]) -> float:
    if not cluster or cluster == "unknown_cluster":
        return 0.0
    counts = _recent_mix(recent_topics, "topic_cluster")
    hits = counts.get(cluster, 0)
    return round(hits * EDITORIAL_FATIGUE_PENALTY_STEP, 4)


def _risk_penalty(item: dict[str, Any]) -> float:
    if item.get("manual_override_note"):
        return 0.0
    if item.get("compliance_risk") == "high" or item.get("actionability_risk") == "high":
        return EDITORIAL_HIGH_RISK_PENALTY
    if item.get("compliance_risk") == "medium" or item.get("actionability_risk") == "medium":
        return EDITORIAL_MEDIUM_RISK_PENALTY
    return 0.0


def _creator_fit_bonus(item: dict[str, Any]) -> float:
    fit = str(item.get("creator_fit") or "")
    if fit == "strong":
        return 0.35
    if fit == "medium":
        return 0.08
    if fit == "weak":
        return -0.4
    return 0.0


def _li_jie_bonus(item: dict[str, Any]) -> float:
    value = str(item.get("li_jie_value") or "")
    if value == "save":
        return 0.4
    if value == "click":
        return 0.18
    if value == "ignore":
        return -0.25
    return 0.0


def _zhang_auntie_bonus(item: dict[str, Any]) -> float:
    value = str(item.get("zhang_auntie_value") or "")
    if value == "forward":
        return 0.45
    if value == "watch":
        return 0.15
    if value == "ignore":
        return -0.28
    return 0.0


def _is_policy_translation_topic(item: dict[str, Any]) -> bool:
    if float(item.get("policy_translation_penalty") or 0.0) <= 0:
        return False
    if any(token in _normalize(_as_text(item.get("title"), item.get("summary"))) for token in HOUSEHOLD_PAIN_HINTS):
        return False
    return True


def _domestic_relevance_penalty(item: dict[str, Any]) -> float:
    source = str(item.get("source") or "")
    if source not in INTERNATIONAL_SOURCES:
        return 0.0
    text = _normalize(
        _as_text(
            item.get("title"),
            item.get("summary"),
            " ".join(item.get("keywords") or []),
            item.get("topic_cluster"),
        )
    )
    line = str(item.get("topic_line_primary") or "")
    cluster = str(item.get("topic_cluster") or "")
    has_domestic_anchor = any(token.lower() in text for token in (hint.lower() for hint in DOMESTIC_RELEVANCE_HINTS))
    has_foreign_context = any(token.lower() in text for token in (hint.lower() for hint in FOREIGN_CONTEXT_HINTS))

    if line == "public_issue":
        if has_foreign_context and not has_domestic_anchor:
            return 0.8
        if source in {"rss_nyt_health", "rss_sciencedaily_health", "stat_pharma"} and not has_domestic_anchor:
            return 0.55
    if line == "family_anxiety":
        if source in {"rss_nyt_health", "rss_sciencedaily_health", "stat_pharma"} and not has_domestic_anchor:
            return 0.3
    if line == "consumer_scam":
        if source == "who_alerts" and cluster == "假药 / 劣药" and not has_domestic_anchor:
            if any(token in text for token in ("爱博新", "ibrance", "palbociclib", "乳腺癌", "靶向药")):
                return 1.0
            return 0.45
    if source == "who_alerts" and cluster not in {"假药 / 劣药", "儿童用药", "药品安全警报"} and not has_domestic_anchor:
        return 0.2
    return 0.0


def _local_shareability_bonus(item: dict[str, Any]) -> float:
    text = _normalize(
        _as_text(
            item.get("title"),
            item.get("summary"),
            " ".join(item.get("keywords") or []),
            item.get("topic_cluster"),
        )
    )
    line = str(item.get("topic_line_primary") or "")
    source = str(item.get("source") or "")
    bonus = 0.0

    if "315" in text and any(token in text for token in ("外泌体", "私域", "健康讲座", "老人", "养老金", "增高")):
        bonus += 0.45

    if any(token in text for token in ("私域", "健康讲座", "老人", "父母", "爸妈", "养老金")) and any(
        token in text for token in ("骗局", "卖货", "讲座", "保健品", "围猎")
    ):
        bonus += 0.35

    if any(token in text for token in ("医保", "报销", "进医保", "开不出来", "用不上", "进院难")):
        bonus += 0.3

    if line in {"family_anxiety", "consumer_scam"} and any(
        token in text for token in (hint.lower() for hint in LOCAL_FAMILY_SHARE_HINTS)
    ):
        bonus += 0.15

    if source == "wechat_rss" and any(token in text for token in ("315", "私域", "外泌体", "医保", "老人")):
        bonus += 0.08

    return round(min(bonus, 0.8), 4)


def _source_preference_bonus(item: dict[str, Any]) -> float:
    source = str(item.get("source") or "")
    line = str(item.get("topic_line_primary") or "")
    text = _normalize(
        _as_text(
            item.get("title"),
            item.get("summary"),
            " ".join(item.get("keywords") or []),
            item.get("topic_cluster"),
        )
    )

    if source == "wechat_rss":
        return 0.18 if any(token in text for token in ("315", "医保", "外泌体", "老人", "家庭", "药盒")) else 0.12
    if source == "baidu_search":
        return 0.12
    if source in {"nmpa_news", "govcn_policy"}:
        return 0.1 if line in {"public_issue", "family_anxiety"} else 0.06
    if source in {"rss_stats_release", "rss_stats_interpretation"}:
        return -0.22
    if source in {"rss_fda_medwatch", "rss_stat_backup", "rss_sciencedaily_health", "rss_nyt_health", "stat_pharma"}:
        return -0.08
    return 0.0


def _policy_translation_penalty(item: dict[str, Any]) -> float:
    line = str(item.get("topic_line_primary") or "")
    if line != "public_issue":
        return 0.0
    text = _normalize(
        _as_text(
            item.get("title"),
            item.get("summary"),
            " ".join(item.get("keywords") or []),
            item.get("topic_cluster"),
        )
    )
    if not any(token in text for token in POLICY_TRANSLATION_HINTS):
        return 0.0
    if any(token in text for token in HOUSEHOLD_PAIN_HINTS):
        return 0.0
    penalty = 0.22
    if any(token in text for token in ("外商独资医院", "双通道", "起付线", "报销比例", "试点")):
        penalty += 0.08
    return round(penalty, 4)


def _source_penalty(sources: list[str]) -> float:
    counts = Counter(source for source in sources if source)
    penalty = 0.0
    for count in counts.values():
        if count > 1:
            penalty += (count - 1) * EDITORIAL_SOURCE_CONCENTRATION_PENALTY
    return round(penalty, 4)


def _normalized_watch_rate(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed * 100 if parsed <= 1 else parsed


def _performance_feedback_bonus(cluster: str, recent_topics: list[dict[str, Any]]) -> float:
    cluster_name = str(cluster or "").strip()
    if not cluster_name:
        return 0.0

    watch_rates: list[float] = []
    for item in recent_topics:
        if str(item.get("topic_cluster") or "").strip() != cluster_name:
            continue
        is_published = any(
            item.get(field) not in (None, "", [])
            for field in ("publish_status", "publish_at", "publish_url")
        )
        if not is_published:
            continue
        watch_rate = _normalized_watch_rate(item.get("perf_watch_rate"))
        if watch_rate is not None:
            watch_rates.append(watch_rate)

    if not watch_rates:
        return 0.0

    avg_watch_rate = sum(watch_rates) / len(watch_rates)
    if avg_watch_rate > 40:
        return 0.1
    if avg_watch_rate < 20:
        return -0.08
    return 0.0


def _requires_public_issue_override(item: dict[str, Any]) -> bool:
    line = str(item.get("topic_line_primary") or "")
    if line != "public_issue":
        return False
    source = str(item.get("source") or "")
    if item.get("manual_override_note"):
        return False
    quality_score = float(item.get("quality_score") or item.get("score_total") or 0.0)
    local_shareability_bonus = float(item.get("local_shareability_bonus") or 0.0)
    text = _normalize(
        _as_text(
            item.get("title"),
            item.get("summary"),
            " ".join(item.get("keywords") or []),
            item.get("topic_cluster"),
        )
    )
    if float(item.get("domestic_relevance_penalty") or 0.0) >= 0.55:
        return True
    if source in INTERNATIONAL_SOURCES and str(item.get("decision_impact_level") or "") == "low":
        return True
    if source not in INTERNATIONAL_SOURCES:
        if quality_score < 4.0 and local_shareability_bonus < 0.3:
            return True
        if any(token in text for token in ("追回医保基金", "监管成果", "专项整治", "工作进展", "最新表态")):
            if not any(token in text for token in ("为什么", "怎么", "还能", "开不出来", "用不上", "药盒", "家庭")):
                return True
    return False


def _presentation_order(selected: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    if len(selected) <= 1:
        return list(selected)
    ordered = _diversified_fallback(selected, top_n=min(top_n, len(selected)), score_field="editorial_priority_score")
    chosen_ids = {id(item) for item in ordered}
    remainder = [item for item in selected if id(item) not in chosen_ids]
    remainder.sort(key=lambda item: item.get("editorial_priority_score") or 0.0, reverse=True)
    return ordered + remainder


def enrich_editorial_scores(
    scored_topics: list[dict[str, Any]],
    recent_topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for topic in scored_topics:
        quality_score = float(topic.get("score_total") or 0.0)
        line_gap_bonus = _line_gap_bonus(str(topic.get("topic_line_primary") or ""), recent_topics)
        role_gap_bonus = _role_gap_bonus(str(topic.get("content_role") or ""), recent_topics, quality_score)
        performance_feedback_bonus = _performance_feedback_bonus(
            str(topic.get("topic_cluster") or ""),
            recent_topics,
        )
        creator_fit_bonus = _creator_fit_bonus(topic)
        li_jie_bonus = _li_jie_bonus(topic)
        zhang_auntie_bonus = _zhang_auntie_bonus(topic)
        fatigue_penalty = (
            _fatigue_penalty(str(topic.get("topic_cluster") or ""), recent_topics)
            if EDITORIAL_PHASE >= 3
            else 0.0
        )
        risk_penalty = _risk_penalty(topic)
        domestic_relevance_penalty = _domestic_relevance_penalty(topic)
        local_shareability_bonus = _local_shareability_bonus(topic)
        source_preference_bonus = _source_preference_bonus(topic)
        policy_translation_penalty = _policy_translation_penalty(topic)
        editorial_priority_score = round(
            quality_score
            + line_gap_bonus
            + role_gap_bonus
            + performance_feedback_bonus
            + creator_fit_bonus
            + li_jie_bonus
            + zhang_auntie_bonus
            + local_shareability_bonus
            + source_preference_bonus
            - fatigue_penalty
            - risk_penalty
            - domestic_relevance_penalty,
            4,
        )
        editorial_priority_score = round(
            editorial_priority_score - policy_translation_penalty,
            4,
        )
        reason_parts = [
            f"quality={quality_score:.2f}",
            f"line_gap=+{line_gap_bonus:.2f}",
            f"role_gap=+{role_gap_bonus:.2f}",
        ]
        if performance_feedback_bonus:
            reason_parts.append(f"history_perf={performance_feedback_bonus:+.2f}")
        if local_shareability_bonus:
            reason_parts.append(f"share=+{local_shareability_bonus:.2f}")
        if creator_fit_bonus:
            reason_parts.append(f"creator_fit={creator_fit_bonus:+.2f}")
        if li_jie_bonus:
            reason_parts.append(f"li_jie={li_jie_bonus:+.2f}")
        if zhang_auntie_bonus:
            reason_parts.append(f"zhang={zhang_auntie_bonus:+.2f}")
        if source_preference_bonus:
            reason_parts.append(f"source_pref={source_preference_bonus:+.2f}")
        if fatigue_penalty:
            reason_parts.append(f"fatigue=-{fatigue_penalty:.2f}")
        if risk_penalty:
            reason_parts.append(f"risk=-{risk_penalty:.2f}")
        if domestic_relevance_penalty:
            reason_parts.append(f"domestic=-{domestic_relevance_penalty:.2f}")
        if policy_translation_penalty:
            reason_parts.append(f"policy=-{policy_translation_penalty:.2f}")
        enriched.append(
            {
                **topic,
                "quality_score": round(quality_score, 4),
                "line_gap_bonus": line_gap_bonus,
                "role_gap_bonus": role_gap_bonus,
                "performance_feedback_bonus": round(performance_feedback_bonus, 4),
                "creator_fit_bonus": round(creator_fit_bonus, 4),
                "li_jie_bonus": round(li_jie_bonus, 4),
                "zhang_auntie_bonus": round(zhang_auntie_bonus, 4),
                "fatigue_penalty": fatigue_penalty,
                "source_concentration_penalty": 0.0,
                "risk_penalty": risk_penalty,
                "domestic_relevance_penalty": domestic_relevance_penalty,
                "local_shareability_bonus": local_shareability_bonus,
                "source_preference_bonus": round(source_preference_bonus, 4),
                "policy_translation_penalty": round(policy_translation_penalty, 4),
                "editorial_priority_score": editorial_priority_score,
                "selection_rank_reason": "; ".join(reason_parts),
            }
        )
    return enriched


def _combo_is_valid(combo: tuple[dict[str, Any], ...], eligible_for_role_gap: bool) -> bool:
    lines = {str(item.get("topic_line_primary") or "") for item in combo if item.get("topic_line_primary") not in {None, "rejected"}}
    roles = {str(item.get("content_role") or "") for item in combo if item.get("content_role")}
    clusters = {str(item.get("topic_cluster") or "") for item in combo if item.get("topic_cluster")}
    if len(lines) < 2:
        return False
    if len(roles) < 2:
        return False
    if len(clusters) <= 1:
        return False
    if not any(item.get("content_role") == "spread" for item in combo):
        return False
    if eligible_for_role_gap and not any(item.get("content_role") in {"save", "followup"} for item in combo):
        return False
    if not any(item.get("topic_line_primary") in {"public_issue", "family_anxiety"} for item in combo):
        return False
    if all(is_official_press_style(item) for item in combo):
        return False
    if sum(1 for item in combo if _is_policy_translation_topic(item)) > 1:
        return False
    return True


def _diversified_fallback(
    candidates: list[dict[str, Any]],
    *,
    top_n: int,
    score_field: str,
) -> list[dict[str, Any]]:
    remaining = list(candidates)
    selected: list[dict[str, Any]] = []
    selected_lines: set[str] = set()
    selected_roles: set[str] = set()
    selected_clusters: set[str] = set()

    while remaining and len(selected) < top_n:
        policy_selected = sum(1 for item in selected if _is_policy_translation_topic(item))

        def _key(item: dict[str, Any]) -> tuple[int, int, int, float]:
            line = str(item.get("topic_line_primary") or "")
            role = str(item.get("content_role") or "")
            cluster = str(item.get("topic_cluster") or "")
            return (
                0 if (_is_policy_translation_topic(item) and policy_selected >= 1) else 1,
                1 if line and line not in selected_lines else 0,
                1 if role and role not in selected_roles else 0,
                1 if cluster and cluster not in selected_clusters else 0,
                float(item.get(score_field) or item.get("score_total") or 0.0),
            )

        pick = max(remaining, key=_key)
        selected.append(pick)
        remaining.remove(pick)
        if pick.get("topic_line_primary"):
            selected_lines.add(str(pick.get("topic_line_primary")))
        if pick.get("content_role"):
            selected_roles.add(str(pick.get("content_role")))
        if pick.get("topic_cluster"):
            selected_clusters.add(str(pick.get("topic_cluster")))

    return selected


def select_topics_for_output(
    scored_topics: list[dict[str, Any]],
    recent_topics: list[dict[str, Any]],
    *,
    phase: int | None = None,
    top_n: int = TOP_N,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    effective_phase = EDITORIAL_PHASE if phase is None else phase
    enriched = enrich_editorial_scores(scored_topics, recent_topics)
    shadow_ranked = sorted(enriched, key=lambda item: item.get("score_total") or 0.0, reverse=True)

    if effective_phase <= 1:
        selected = []
        for index, topic in enumerate(shadow_ranked[:top_n], start=1):
            selected.append(
                {
                    **topic,
                    "selection_rank_reason": f"Phase 1 shadow mode: 仍按 score_total 排序，第 {index} 位。",
                }
            )
        return selected, {"phase": effective_phase, "mode": "shadow", "eligible_count": len(shadow_ranked)}

    filtered = [
        topic
        for topic in enriched
        if topic.get("reject_type") == "none"
        and topic.get("topic_line_primary") != "rejected"
        and topic.get("risk_penalty", 0.0) < EDITORIAL_HIGH_RISK_PENALTY
        and not _requires_public_issue_override(topic)
        and not (
            str(topic.get("creator_fit") or "") == "weak"
            and str(topic.get("li_jie_value") or "") == "ignore"
            and str(topic.get("zhang_auntie_value") or "") == "ignore"
        )
    ]
    filtered.sort(key=lambda item: item.get("editorial_priority_score") or 0.0, reverse=True)
    pool = filtered[: max(top_n * 4, top_n)]
    has_role_qualified = any(
        topic.get("content_role") in {"save", "followup"}
        and float(topic.get("quality_score") or 0.0) >= EDITORIAL_ROLE_BASELINE_THRESHOLD
        for topic in pool
    )

    best_combo: tuple[dict[str, Any], ...] | None = None
    best_score = float("-inf")
    for combo in combinations(pool, min(top_n, len(pool))):
        if not _combo_is_valid(combo, has_role_qualified):
            continue
        combo_sources = [str(item.get("source") or "") for item in combo]
        source_penalty = _source_penalty(combo_sources) if effective_phase >= 3 else 0.0
        combo_score = sum(float(item.get("editorial_priority_score") or 0.0) for item in combo) - source_penalty
        if combo_score > best_score:
            best_score = combo_score
            best_combo = combo

    if best_combo is None:
        fallback_pool = filtered or shadow_ranked
        score_field = "editorial_priority_score" if filtered else "score_total"
        fallback = _diversified_fallback(fallback_pool, top_n=top_n, score_field=score_field)
        return fallback, {
            "phase": effective_phase,
            "mode": "fallback_diversified",
            "eligible_count": len(filtered),
            "reason": "No combo satisfied editorial constraints; fell back to diversified priority selection.",
        }

    source_penalty = _source_penalty([str(item.get("source") or "") for item in best_combo]) if effective_phase >= 3 else 0.0
    selected: list[dict[str, Any]] = []
    for topic in best_combo:
        selected.append(
            {
                **topic,
                "source_concentration_penalty": source_penalty,
                "editorial_priority_score": round(
                    float(topic.get("editorial_priority_score") or 0.0) - source_penalty,
                    4,
                ),
                "selection_rank_reason": (
                    f"{topic.get('selection_rank_reason')}; "
                    f"editorial_priority={topic.get('editorial_priority_score')}; "
                    f"phase={effective_phase}"
                ),
            }
        )
    selected = _presentation_order(selected, top_n)
    return selected, {
        "phase": effective_phase,
        "mode": "editorial_selection",
        "eligible_count": len(filtered),
    }
