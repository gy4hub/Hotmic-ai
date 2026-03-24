from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from secrets import token_hex
from typing import Any

from compat import UTC
REPO_ROOT = Path(__file__).resolve().parent.parent
WEIGHTS_DIR = REPO_ROOT / 'config'
PLATFORMS = ['douyin', 'xiaohongshu', 'shipinhao']
SOURCE_WEIGHTS_PATH = WEIGHTS_DIR / 'source_weights.json'
SCORING_HISTORY_DIR = WEIGHTS_DIR / 'scoring_history'
SCORING_PREVIEW_DIR = WEIGHTS_DIR / 'scoring_previews'

DIMENSION_META = {
    'emotion': {'label': '情绪强度'},
    'timely': {'label': '时效稀缺性'},
    'subvert': {'label': '认知颠覆度'},
    'relate': {'label': '读者自我关联'},
    'spread': {'label': '传播动机'},
    'tension': {'label': '叙事张力'},
    'depth': {'label': '内容深度'},
}

DEFAULT_SOURCE_WEIGHT_BY_BUCKET = {
    'official': 0.3,
    'trusted_rss': 0.22,
    'platform_native': 0.16,
    'industry_media': 0.12,
    'social_rss': 0.08,
    'search': 0.05,
    'other': 0.0,
}

SOURCE_BUCKET_LABELS = {
    'official': '官方监管源',
    'trusted_rss': '可信 RSS',
    'platform_native': '平台原生',
    'industry_media': '行业媒体',
    'social_rss': '社交 RSS',
    'search': '搜索补充',
    'other': '其他',
}


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _weight_path(platform: str) -> Path:
    return WEIGHTS_DIR / f'weights_{platform}.json'


def load_platform_weights(platform: str) -> dict[str, float]:
    with _weight_path(platform).open('r', encoding='utf-8') as f:
        return json.load(f)


def save_platform_weights(platform: str, weights: dict[str, float]) -> None:
    with _weight_path(platform).open('w', encoding='utf-8') as f:
        json.dump(weights, f, ensure_ascii=False, indent=2)
        f.write('\n')


def load_all_platform_weights() -> dict[str, dict[str, float]]:
    return {platform: load_platform_weights(platform) for platform in PLATFORMS}


def load_source_weights() -> dict[str, float]:
    if not SOURCE_WEIGHTS_PATH.exists():
        save_source_weights(DEFAULT_SOURCE_WEIGHT_BY_BUCKET)
        return deepcopy(DEFAULT_SOURCE_WEIGHT_BY_BUCKET)
    with SOURCE_WEIGHTS_PATH.open('r', encoding='utf-8') as f:
        data = json.load(f)
    merged = deepcopy(DEFAULT_SOURCE_WEIGHT_BY_BUCKET)
    merged.update({k: float(v) for k, v in data.items() if k in merged})
    return merged


def save_source_weights(weights: dict[str, float]) -> None:
    merged = deepcopy(DEFAULT_SOURCE_WEIGHT_BY_BUCKET)
    merged.update({k: float(v) for k, v in weights.items() if k in merged})
    with SOURCE_WEIGHTS_PATH.open('w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write('\n')


def current_scoring_state() -> dict[str, Any]:
    return {
        'platform_weights': load_all_platform_weights(),
        'source_weights': load_source_weights(),
    }


def create_scoring_snapshot(
    *,
    reason: str,
    instruction: str | None = None,
    patch: dict[str, Any] | None = None,
    actor: str = 'system',
) -> dict[str, Any]:
    history_dir = _ensure_dir(SCORING_HISTORY_DIR)
    snapshot_id = f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}_{token_hex(4)}"
    payload = {
        'snapshot_id': snapshot_id,
        'created_at': _utc_now_iso(),
        'actor': actor,
        'reason': reason,
        'instruction': instruction,
        'patch': patch or {},
        'state': current_scoring_state(),
    }
    path = history_dir / f'{snapshot_id}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {
        'snapshot_id': snapshot_id,
        'created_at': payload['created_at'],
        'reason': reason,
        'instruction': instruction,
        'path': str(path),
    }


def list_scoring_history(limit: int = 20) -> list[dict[str, Any]]:
    history_dir = _ensure_dir(SCORING_HISTORY_DIR)
    items: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob('*.json'), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        state = payload.get('state') or {}
        items.append(
            {
                'snapshot_id': payload.get('snapshot_id') or path.stem,
                'created_at': payload.get('created_at'),
                'actor': payload.get('actor') or 'system',
                'reason': payload.get('reason') or '',
                'instruction': payload.get('instruction'),
                'patch': payload.get('patch') or {},
                'platform_count': len(state.get('platform_weights') or {}),
                'source_bucket_count': len(state.get('source_weights') or {}),
            }
        )
        if len(items) >= max(limit, 1):
            break
    return items


def load_scoring_snapshot(snapshot_id: str) -> dict[str, Any]:
    path = _ensure_dir(SCORING_HISTORY_DIR) / f'{snapshot_id}.json'
    if not path.exists():
        raise FileNotFoundError(f'Scoring snapshot not found: {snapshot_id}')
    return json.loads(path.read_text(encoding='utf-8'))


def restore_scoring_snapshot(snapshot_id: str) -> dict[str, Any]:
    payload = load_scoring_snapshot(snapshot_id)
    state = payload.get('state') or {}
    platform_weights = state.get('platform_weights') or {}
    source_weights = state.get('source_weights') or {}
    for platform in PLATFORMS:
        weights = platform_weights.get(platform)
        if isinstance(weights, dict):
            save_platform_weights(platform, weights)
    save_source_weights(source_weights)
    return {
        'snapshot_id': snapshot_id,
        'restored_at': _utc_now_iso(),
        'reason': payload.get('reason'),
        'instruction': payload.get('instruction'),
        'current_config': scoring_overview(),
    }


def create_scoring_preview(*, instruction: str, patch: dict[str, Any], usage: dict[str, Any] | None = None) -> dict[str, Any]:
    preview_dir = _ensure_dir(SCORING_PREVIEW_DIR)
    preview_id = f"preview_{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}_{token_hex(4)}"
    payload = {
        'preview_id': preview_id,
        'created_at': _utc_now_iso(),
        'instruction': instruction,
        'patch': patch,
        'usage': usage or {},
    }
    path = preview_dir / f'{preview_id}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {
        'preview_id': preview_id,
        'created_at': payload['created_at'],
        'instruction': instruction,
        'path': str(path),
    }


def load_scoring_preview(preview_id: str) -> dict[str, Any]:
    path = _ensure_dir(SCORING_PREVIEW_DIR) / f'{preview_id}.json'
    if not path.exists():
        raise FileNotFoundError(f'Scoring preview not found: {preview_id}')
    return json.loads(path.read_text(encoding='utf-8'))


def scoring_overview() -> dict:
    return {
        'dimensions': DIMENSION_META,
        'platform_weights': load_all_platform_weights(),
        'source_bonus': load_source_weights(),
        'source_bucket_labels': SOURCE_BUCKET_LABELS,
        'formula': {
            'base': '按平台维度权重做加权平均',
            'source_bonus': '再叠加信息源层级加分',
            'final': 'final_score = best_platform_weighted_score + source_weight_bonus',
        },
    }
