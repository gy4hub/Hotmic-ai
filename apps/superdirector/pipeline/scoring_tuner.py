from __future__ import annotations

import json
from typing import Any

from config import GEMINI_API_KEY, GEMINI_FLASH_MODEL, QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL
from pipeline.pricing import estimate_cost_usd
from pipeline.scoring_config import (
    DIMENSION_META,
    PLATFORMS,
    SOURCE_BUCKET_LABELS,
    WEIGHTS_DIR,
    SOURCE_WEIGHTS_PATH,
    load_all_platform_weights,
    load_source_weights,
)
from pipeline.utils import request_with_retry

GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta'
SOURCE_BUCKETS = list(SOURCE_BUCKET_LABELS.keys())


def _usage_summary(provider: str, model: str, endpoint: str, usage: dict) -> dict:
    prompt_tokens = (
        usage.get('prompt_tokens')
        or usage.get('promptTokenCount')
        or usage.get('promptTokens')
    )
    output_tokens = (
        usage.get('completion_tokens')
        or usage.get('candidatesTokenCount')
        or usage.get('outputTokens')
    )
    cost_usd = estimate_cost_usd(provider, model, prompt_tokens, output_tokens)
    return {
        'provider': provider,
        'model': model,
        'endpoint': endpoint,
        'input_tokens': prompt_tokens,
        'output_tokens': output_tokens,
        'cost_usd': cost_usd,
        'estimated_cost_usd': cost_usd,
    }


def _clamp_weight(value: Any) -> float:
    parsed = float(value)
    return round(min(max(parsed, 0.0), 3.0), 4)


def _current_config() -> dict:
    return {
        'dimensions': {k: v['label'] for k, v in DIMENSION_META.items()},
        'platform_weights': load_all_platform_weights(),
        'source_weights': load_source_weights(),
        'source_bucket_labels': SOURCE_BUCKET_LABELS,
    }


def _build_prompt(instruction: str) -> str:
    return (
        '你是选题评分系统的配置解析器。\n'
        '任务：把用户关于“如何调整选题打分偏好”的自然语言，转换成结构化 JSON。\n'
        '允许调整的对象只有两类：\n'
        '1. platform_weights: 平台维度权重（douyin/xiaohongshu/shipinhao）\n'
        '2. source_weights: 来源桶加分（official/trusted_rss/platform_native/industry_media/social_rss/search/other）\n\n'
        f'维度定义：{json.dumps({k: v["label"] for k, v in DIMENSION_META.items()}, ensure_ascii=False)}\n'
        f'当前配置：{json.dumps(_current_config(), ensure_ascii=False)}\n\n'
        '输出 JSON，格式固定为：\n'
        '{\n'
        '  "summary": "一句话总结用户想怎么调",\n'
        '  "platform_weights": {"douyin": {"emotion": 1.6}, "xiaohongshu": {}, "shipinhao": {}},\n'
        '  "source_weights": {"official": 0.25},\n'
        '  "notes": ["如果用户表达模糊，这里写风险提醒"]\n'
        '}\n'
        '规则：\n'
        '- 只返回 JSON，不要 markdown。\n'
        '- 用户如果说“提高/降低”，请根据当前值给出一个合理的新值，单次调整尽量温和。\n'
        '- 未提到的字段不要瞎改。\n'
        '- 如果意思不明确，就尽量少改，并把风险写进 notes。\n\n'
        f'用户指令：{instruction}'
    )


async def _parse_with_qwen(int_client, instruction: str) -> tuple[dict, dict]:
    payload = {
        'model': QWEN_MODEL,
        'messages': [
            {'role': 'system', 'content': '你是 JSON 配置转换器。只返回 JSON。'},
            {'role': 'user', 'content': _build_prompt(instruction)},
        ],
        'response_format': {'type': 'json_object'},
    }
    resp = await request_with_retry(
        int_client,
        'POST',
        f'{QWEN_BASE_URL}/chat/completions',
        headers={
            'Authorization': f'Bearer {QWEN_API_KEY}',
            'Content-Type': 'application/json; charset=utf-8',
        },
        content=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
    )
    resp.raise_for_status()
    data = resp.json()
    content = data.get('choices', [{}])[0].get('message', {}).get('content', '{}')
    return json.loads(content), _usage_summary('qwen', QWEN_MODEL, 'chat.completions', data.get('usage', {}))


async def _parse_with_gemini(ext_client, instruction: str) -> tuple[dict, dict]:
    payload = {
        'contents': [{'parts': [{'text': _build_prompt(instruction)}]}],
        'generationConfig': {'responseMimeType': 'application/json'},
    }
    resp = await request_with_retry(
        ext_client,
        'POST',
        f'{GEMINI_BASE}/models/{GEMINI_FLASH_MODEL}:generateContent',
        headers={'x-goog-api-key': GEMINI_API_KEY, 'Content-Type': 'application/json'},
        json=payload,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
    return json.loads(text), _usage_summary('google', GEMINI_FLASH_MODEL, 'generateContent', data.get('usageMetadata', {}))


async def parse_scoring_instruction(ext_client, int_client, instruction: str) -> tuple[dict, dict]:
    if QWEN_API_KEY:
        return await _parse_with_qwen(int_client, instruction)
    if GEMINI_API_KEY:
        return await _parse_with_gemini(ext_client, instruction)
    raise RuntimeError('No Qwen or Gemini API key configured for scoring tuning.')


def _validate_patch(parsed: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    patch = {
        'summary': parsed.get('summary') or '',
        'notes': parsed.get('notes') if isinstance(parsed.get('notes'), list) else [],
        'platform_weights': {platform: {} for platform in PLATFORMS},
        'source_weights': {},
    }

    raw_platform = parsed.get('platform_weights') if isinstance(parsed.get('platform_weights'), dict) else {}
    for platform, changes in raw_platform.items():
        if platform not in PLATFORMS:
            errors.append(f'Unknown platform: {platform}')
            continue
        if not isinstance(changes, dict):
            continue
        for dimension, value in changes.items():
            if dimension not in DIMENSION_META:
                errors.append(f'Unknown dimension: {dimension}')
                continue
            try:
                patch['platform_weights'][platform][dimension] = _clamp_weight(value)
            except Exception:
                errors.append(f'Invalid weight for {platform}.{dimension}: {value}')

    raw_source = parsed.get('source_weights') if isinstance(parsed.get('source_weights'), dict) else {}
    for bucket, value in raw_source.items():
        if bucket not in SOURCE_BUCKETS:
            errors.append(f'Unknown source bucket: {bucket}')
            continue
        try:
            patch['source_weights'][bucket] = _clamp_weight(value)
        except Exception:
            errors.append(f'Invalid source weight for {bucket}: {value}')

    return patch, errors


async def interpret_scoring_instruction(ext_client, int_client, instruction: str) -> tuple[dict, dict, list[str]]:
    parsed, usage = await parse_scoring_instruction(ext_client, int_client, instruction)
    patch, errors = _validate_patch(parsed if isinstance(parsed, dict) else {})
    return patch, usage, errors


def apply_scoring_patch(parsed: dict) -> dict:
    changed_platforms: dict[str, dict[str, float]] = {}
    current_platform_weights = load_all_platform_weights()
    for platform, changes in (parsed.get('platform_weights') or {}).items():
        if platform not in PLATFORMS or not isinstance(changes, dict):
            continue
        updated = dict(current_platform_weights[platform])
        changed_fields = {}
        for dimension, value in changes.items():
            if dimension not in DIMENSION_META:
                continue
            updated_value = _clamp_weight(value)
            if updated.get(dimension) != updated_value:
                updated[dimension] = updated_value
                changed_fields[dimension] = updated_value
        if changed_fields:
            (WEIGHTS_DIR / f'weights_{platform}.json').write_text(
                json.dumps(updated, ensure_ascii=False, indent=2) + '\n',
                encoding='utf-8',
            )
            changed_platforms[platform] = changed_fields

    source_weights = load_source_weights()
    changed_source_weights = {}
    updated_source_weights = dict(source_weights)
    for bucket, value in (parsed.get('source_weights') or {}).items():
        if bucket not in updated_source_weights:
            continue
        updated_value = _clamp_weight(value)
        if updated_source_weights.get(bucket) != updated_value:
            updated_source_weights[bucket] = updated_value
            changed_source_weights[bucket] = updated_value
    if changed_source_weights:
        SOURCE_WEIGHTS_PATH.write_text(
            json.dumps(updated_source_weights, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )

    return {
        'summary': parsed.get('summary'),
        'notes': parsed.get('notes') or [],
        'changed_platforms': changed_platforms,
        'changed_source_weights': changed_source_weights,
        'current_config': _current_config(),
    }
