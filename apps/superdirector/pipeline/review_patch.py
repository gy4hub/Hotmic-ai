from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import config as app_config
from config import CASEY_PROFILE_PATH, HOTMIC_ROOT_PATH, HOTMIC_STYLE_DB_PATH, load_casey_profile


def _load_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return data


def _save_json(path: str | Path, data: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _clamp_weight(value: float) -> float:
    return round(min(max(float(value), 0.0), 1.0), 4)


def _normalize_weight_map(weights: dict[str, float]) -> dict[str, float]:
    cleaned = {key: max(float(value), 0.0) for key, value in weights.items()}
    total = sum(cleaned.values())
    if total <= 0:
        return {key: round(1.0 / len(cleaned), 4) for key in cleaned} if cleaned else {}
    normalized = {key: round(value / total, 4) for key, value in cleaned.items()}
    drift = round(1.0 - sum(normalized.values()), 4)
    if normalized and drift:
        first_key = next(iter(normalized))
        normalized[first_key] = round(normalized[first_key] + drift, 4)
    return normalized


def _rebalance_line_weights(current: dict[str, float], target_key: str, delta: float) -> dict[str, float]:
    if target_key not in current:
        raise KeyError(target_key)

    starting = _normalize_weight_map(current)
    original_target = starting[target_key]
    target_weight = _clamp_weight(original_target + float(delta))
    other_keys = [key for key in starting if key != target_key]
    remaining = round(1.0 - target_weight, 4)

    if not other_keys:
        return {target_key: 1.0}

    other_total = sum(starting[key] for key in other_keys)
    if other_total <= 0:
        even_share = round(remaining / len(other_keys), 4)
        result = {target_key: target_weight}
        for key in other_keys:
            result[key] = even_share
        drift = round(1.0 - sum(result.values()), 4)
        result[other_keys[0]] = round(result[other_keys[0]] + drift, 4)
        return result

    result = {target_key: target_weight}
    for key in other_keys:
        result[key] = round((starting[key] / other_total) * remaining, 4)
    drift = round(1.0 - sum(result.values()), 4)
    result[other_keys[0]] = round(result[other_keys[0]] + drift, 4)
    return result


def _line_alias_map(profile: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    lines = ((profile.get("content_mix") or {}).get("lines") or [])
    alias_to_key: dict[str, str] = {}
    for entry in lines:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if not key:
            continue
        candidates = [key, entry.get("name")]
        candidates.extend(entry.get("aliases") or [])
        for candidate in candidates:
            normalized = _normalize_text(candidate)
            if normalized:
                alias_to_key[normalized] = key
    return alias_to_key, lines


def _refresh_runtime_editorial_mix(updated_weights: dict[str, float]) -> None:
    app_config.EDITORIAL_TARGET_MIX_DEFAULT.clear()
    app_config.EDITORIAL_TARGET_MIX_DEFAULT.update(updated_weights)

    try:
        from pipeline import editorial

        editorial.EDITORIAL_TARGET_MIX_DEFAULT.clear()
        editorial.EDITORIAL_TARGET_MIX_DEFAULT.update(updated_weights)
    except Exception:
        pass


def apply_sd_weight_patch(
    sd_weight_patch: dict[str, Any],
    *,
    profile_path: str | Path | None = None,
) -> dict[str, Any]:
    target_path = Path(profile_path or CASEY_PROFILE_PATH)
    profile = load_casey_profile(target_path)
    alias_map, lines = _line_alias_map(profile)
    if not lines:
        raise ValueError("Profile content_mix.lines is missing")

    current_weights = {
        str(entry.get("key")): float(entry.get("weight") or 0.0)
        for entry in lines
        if isinstance(entry, dict) and str(entry.get("key") or "").strip()
    }
    if not current_weights:
        raise ValueError("Profile content_mix.lines has no valid keyed entries")

    applied: dict[str, dict[str, Any]] = {}
    updated_weights = dict(current_weights)

    for raw_name, patch in (sd_weight_patch or {}).items():
        normalized_name = _normalize_text(raw_name)
        target_key = alias_map.get(normalized_name)
        if not target_key:
            raise ValueError(f"Unknown content line for sd_weight_patch: {raw_name}")
        if not isinstance(patch, dict):
            raise ValueError(f"Invalid patch payload for {raw_name}")
        delta = float(patch.get("delta") or 0.0)
        updated_weights = _rebalance_line_weights(updated_weights, target_key, delta)
        applied[target_key] = {
            "line_name": raw_name,
            "delta": round(delta, 4),
            "reason": str(patch.get("reason") or "").strip(),
            "new_weight": updated_weights[target_key],
        }

    updated_profile = deepcopy(profile)
    updated_lines = []
    for entry in (updated_profile.get("content_mix") or {}).get("lines") or []:
        if not isinstance(entry, dict):
            updated_lines.append(entry)
            continue
        key = str(entry.get("key") or "").strip()
        if key in updated_weights:
            updated_lines.append({**entry, "weight": updated_weights[key]})
        else:
            updated_lines.append(entry)
    updated_profile.setdefault("content_mix", {})["lines"] = updated_lines
    _save_json(target_path, updated_profile)
    _refresh_runtime_editorial_mix(updated_weights)

    return {
        "profile_path": str(target_path),
        "applied": applied,
        "updated_weights": updated_weights,
    }


@lru_cache(maxsize=1)
def _hotmic_update_style_module():
    script_path = Path(HOTMIC_ROOT_PATH) / "hotmic-style-learner" / "scripts" / "update_style_db.py"
    if not script_path.exists():
        raise FileNotFoundError(f"HotMic style learner script not found: {script_path}")

    spec = importlib.util.spec_from_file_location("hotmic_update_style_db", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load HotMic style learner script: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apply_style_patch(
    style_patch: list[dict[str, Any]],
    *,
    style_db_path: str | Path | None = None,
) -> dict[str, Any]:
    target_path = Path(style_db_path or HOTMIC_STYLE_DB_PATH)
    module = _hotmic_update_style_module()
    db = module.load_style_db(str(target_path))
    rules = db.setdefault("rules", [])

    created = 0
    updated = 0
    applied_rules: list[dict[str, Any]] = []

    for patch in style_patch or []:
        if not isinstance(patch, dict):
            continue
        action_text = str(patch.get("action") or "").strip()
        evidence_text = str(patch.get("rule") or "").strip()
        rule_text = action_text or evidence_text
        if not rule_text:
            continue

        candidate = {
            "category": str(patch.get("category") or "review_patch"),
            "rule": rule_text,
        }
        confidence = round(float(patch.get("confidence") or 0.3), 2)
        matching = module.find_matching_rule(candidate, rules)
        if matching:
            matching["confidence"] = round(max(float(matching.get("confidence") or 0.0), confidence), 2)
            matching["last_validated"] = patch.get("last_validated") or matching.get("last_validated")
            if evidence_text:
                matching["evidence"] = evidence_text
            updated += 1
            applied_rules.append({"id": matching.get("id"), "rule": matching.get("rule"), "status": "updated"})
            continue

        new_rule = {
            "id": module.generate_rule_id(rules),
            "category": candidate["category"],
            "rule": candidate["rule"],
            "confidence": confidence,
            "source_diffs": ["review_patch"],
            "created_at": patch.get("created_at") or module.datetime.now().strftime("%Y-%m-%d"),
            "last_validated": patch.get("last_validated") or module.datetime.now().strftime("%Y-%m-%d"),
            "status": str(patch.get("status") or "candidate"),
        }
        if evidence_text:
            new_rule["evidence"] = evidence_text
        rules.append(new_rule)
        created += 1
        applied_rules.append({"id": new_rule["id"], "rule": new_rule["rule"], "status": "created"})

    module.save_style_db(db, str(target_path))
    return {
        "style_db_path": str(target_path),
        "created": created,
        "updated": updated,
        "applied_rules": applied_rules,
    }


def apply_review_patch(
    payload: dict[str, Any],
    *,
    profile_path: str | Path | None = None,
    style_db_path: str | Path | None = None,
) -> dict[str, Any]:
    weight_result = apply_sd_weight_patch(payload.get("sd_weight_patch") or {}, profile_path=profile_path)
    style_result = apply_style_patch(payload.get("style_patch") or [], style_db_path=style_db_path)
    return {
        "sd_weight_patch": weight_result,
        "style_patch": style_result,
    }
