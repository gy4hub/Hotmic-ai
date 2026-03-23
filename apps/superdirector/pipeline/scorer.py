from config import PLATFORMS
from pipeline.scoring_config import (
    DIMENSION_META,
    DEFAULT_SOURCE_WEIGHT_BY_BUCKET,
    load_all_platform_weights,
    load_source_weights,
)
from pipeline.editorial import editorial_config_summary
DIMENSION_METADATA = {
    key: {
        "label": value["label"],
        "desc": "",
    }
    for key, value in DIMENSION_META.items()
}
SOURCE_BUCKETS = {
    "wechat_rss": "trusted_rss",
    "rss_stats_release": "other",
    "rss_stats_interpretation": "other",
    "rss_fda_medwatch": "industry_media",
    "rss_stat_backup": "industry_media",
    "rss_sciencedaily_health": "industry_media",
    "rss_nyt_health": "industry_media",
    "baidu_search": "search",
    "nmpa_news": "official",
    "govcn_policy": "official",
    "fda_safety": "official",
    "who_alerts": "official",
    "stat_pharma": "industry_media",
    "mediacrawler_douyin": "platform_native",
    "mediacrawler_xhs": "platform_native",
}
def load_platform_weights() -> dict[str, dict]:
    return load_all_platform_weights()


def get_scoring_config() -> dict:
    return {
        "dimensions": DIMENSION_METADATA,
        "platform_weights": load_platform_weights(),
        "source_buckets": SOURCE_BUCKETS,
        "source_weights": load_source_weights(),
        "editorial": editorial_config_summary(),
        "formula": {
            "platform_score": "sum(raw_dimension_score * platform_weight) / sum(platform_weight)",
            "final_score": "best_platform_score + source_weight_bonus",
            "editorial_priority_score": "quality_score + line_gap_bonus + role_gap_bonus - fatigue_penalty - risk_penalty - source_concentration_penalty",
        },
    }


def _weighted_total(scores: dict, weights: dict) -> float:
    total_weight = 0.0
    total = 0.0
    for k, w in weights.items():
        if k not in scores:
            continue
        total_weight += w
        total += float(scores[k]) * float(w)
    if total_weight == 0:
        return 0.0
    return round(total / total_weight, 4)


def _source_bucket(source: str | None) -> str:
    if not source:
        return "other"
    if source in SOURCE_BUCKETS:
        return SOURCE_BUCKETS[source]
    if source.startswith("brave_"):
        return "search"
    return "other"


def _apply_source_bonus(score_total: float, source: str | None) -> tuple[float, str, float]:
    bucket = _source_bucket(source)
    bonus = load_source_weights().get(bucket, 0.0)
    return round(score_total + bonus, 4), bucket, bonus


def explain_scores(scores: dict, source: str | None) -> dict:
    platform_weights = load_platform_weights()
    platform_breakdown: dict[str, dict] = {}
    for platform, weights in platform_weights.items():
        weighted_average = _weighted_total(scores, weights)
        contributions = []
        for dimension, weight in weights.items():
            raw_score = float(scores.get(dimension) or 0.0)
            contributions.append(
                {
                    "dimension": dimension,
                    "label": DIMENSION_METADATA.get(dimension, {}).get("label", dimension),
                    "raw_score": raw_score,
                    "weight": float(weight),
                    "weighted_score": round(raw_score * float(weight), 4),
                }
            )
        platform_breakdown[platform] = {
            "weighted_average": weighted_average,
            "weights": weights,
            "contributions": contributions,
        }

    if platform_breakdown:
        best_platform = max(platform_breakdown, key=lambda platform: platform_breakdown[platform]["weighted_average"])
        best_score = platform_breakdown[best_platform]["weighted_average"]
    else:
        best_platform = None
        best_score = 0.0
    final_score, source_tier, source_weight_bonus = _apply_source_bonus(best_score, source)
    return {
        "dimensions": DIMENSION_METADATA,
        "platforms": platform_breakdown,
        "selected_platform": best_platform,
        "base_score": best_score,
        "source": source,
        "source_tier": source_tier,
        "source_weight_bonus": source_weight_bonus,
        "final_score": final_score,
    }


def score_topics(analyzed: list[dict]) -> tuple[list[dict], list[dict]]:
    platform_weights = load_platform_weights()
    score_details: list[dict] = []
    scored: list[dict] = []

    for t in analyzed:
        scores = t.get("scores", {}) or {}
        platform_scores = {}
        for platform, weights in platform_weights.items():
            platform_scores[platform] = _weighted_total(scores, weights)
            for dim, w in weights.items():
                score_details.append(
                    {
                        "topic_id": t.get("topic_id"),
                        "dimension": dim,
                        "raw_score": scores.get(dim),
                        "weighted_score": (scores.get(dim) or 0) * w,
                        "platform": platform,
                        "weight_version": "v1",
                    }
                )

        if platform_scores:
            best_platform = max(platform_scores, key=platform_scores.get)
            score_total = platform_scores[best_platform]
        else:
            best_platform = None
            score_total = 0.0
        score_total, source_tier, source_weight_bonus = _apply_source_bonus(
            score_total,
            t.get("source"),
        )

        scored.append(
            {
                **t,
                "platform_priority": best_platform,
                "quality_score": score_total,
                "score_total": score_total,
                "source_tier": source_tier,
                "source_weight_bonus": source_weight_bonus,
                "score_emotion": scores.get("emotion"),
                "score_timely": scores.get("timely"),
                "score_subvert": scores.get("subvert"),
                "score_relate": scores.get("relate"),
                "score_spread": scores.get("spread"),
                "score_tension": scores.get("tension"),
                "score_depth": scores.get("depth"),
            }
        )

    scored.sort(key=lambda x: x.get("score_total", 0), reverse=True)
    return scored, score_details
