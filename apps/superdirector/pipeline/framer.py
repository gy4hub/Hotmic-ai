import json
import asyncio
from pathlib import Path
from typing import Callable, Awaitable
from config import (
    GEMINI_API_KEY,
    GEMINI_FLASH_MODEL,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_MODEL,
    is_mock_mode,
)
from pipeline.frame_gate import frame_quality_gate
from pipeline.utils import request_with_retry
from pipeline.types import TopicPayload, UsageSummary

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _prompt_from_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _prompt_path(platform: str, *, lite: bool = False) -> str:
    if lite:
        return str(
            Path(__file__).resolve().parent.parent / "config" / "prompts" / "generate_frame_lite.txt"
        )
    return str(
        Path(__file__).resolve().parent.parent / "config" / "prompts" / f"generate_frame_{platform}.txt"
    )


def _usage_summary(provider: str, model: str, endpoint: str, usage: dict) -> UsageSummary:
    prompt_tokens = (
        usage.get("prompt_tokens")
        or usage.get("promptTokenCount")
        or usage.get("promptTokens")
        or 0
    )
    output_tokens = (
        usage.get("completion_tokens")
        or usage.get("candidatesTokenCount")
        or usage.get("outputTokens")
        or 0
    )
    return {
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens,
    }


async def _frame_with_qwen(
    int_client,
    topic: TopicPayload,
    *,
    lite: bool = False,
) -> tuple[TopicPayload, UsageSummary]:
    platform = topic.get("platform_priority") or "douyin"
    prompt = _prompt_from_file(_prompt_path(platform, lite=lite))

    payload = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "TOPIC_JSON=\n" + json.dumps(topic, ensure_ascii=False),
            },
        ],
        "response_format": {"type": "json_object"},
    }

    url = f"{QWEN_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {QWEN_API_KEY}",
        "Content-Type": "application/json; charset=utf-8",
    }

    content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp = await request_with_retry(int_client, "POST", url, headers=headers, content=content)
    resp.raise_for_status()
    data = resp.json()
    content = (
        data.get("choices", [{}])[0].get("message", {}).get("content", "")
    )
    frame = json.loads(content)
    return (
        {**topic, "frame": frame, "frame_tier": "lite" if lite else "full"},
        _usage_summary("qwen", QWEN_MODEL, "chat.completions", data.get("usage", {})),
    )


async def _frame_with_gemini(
    ext_client,
    topic: TopicPayload,
    *,
    lite: bool = False,
) -> tuple[TopicPayload, UsageSummary]:
    platform = topic.get("platform_priority") or "douyin"
    prompt = _prompt_from_file(_prompt_path(platform, lite=lite))

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                        + "\n\nTOPIC_JSON=\n"
                        + json.dumps(topic, ensure_ascii=False)
                    }
                ]
            }
        ],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    url = f"{GEMINI_BASE}/models/{GEMINI_FLASH_MODEL}:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}

    resp = await request_with_retry(ext_client, "POST", url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    text = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    frame = json.loads(text)
    return (
        {**topic, "frame": frame, "frame_tier": "lite" if lite else "full"},
        _usage_summary(
            "google",
            GEMINI_FLASH_MODEL,
            "generateContent",
            data.get("usageMetadata", {}),
        ),
    )


def _merge_usage(base: UsageSummary, extra: UsageSummary) -> UsageSummary:
    if not extra:
        return base
    if not base:
        return dict(extra)
    merged = dict(base)
    merged["provider"] = extra.get("provider") or merged.get("provider")
    merged["model"] = extra.get("model") or merged.get("model")
    merged["endpoint"] = extra.get("endpoint") or merged.get("endpoint")
    merged["input_tokens"] = (merged.get("input_tokens") or 0) + (extra.get("input_tokens") or 0)
    merged["output_tokens"] = (merged.get("output_tokens") or 0) + (extra.get("output_tokens") or 0)
    return merged


async def _frame_topic(ext_client, int_client, topic: TopicPayload) -> tuple[TopicPayload, UsageSummary]:
    frame_func: Callable[..., Awaitable[tuple[TopicPayload, UsageSummary]]]
    client = int_client if QWEN_API_KEY else ext_client
    frame_func = _frame_with_qwen if QWEN_API_KEY else _frame_with_gemini

    aggregated_usage: UsageSummary = {}
    full_error = ""
    try:
        full_result, full_usage = await frame_func(client, topic, lite=False)
        aggregated_usage = _merge_usage(aggregated_usage, full_usage)
        passed, _reason = frame_quality_gate(full_result)
        if passed:
            return full_result, aggregated_usage
    except Exception as exc:  # noqa: BLE001
        full_error = str(exc)

    try:
        lite_result, lite_usage = await frame_func(client, topic, lite=True)
        aggregated_usage = _merge_usage(aggregated_usage, lite_usage)
        passed, reason = frame_quality_gate(lite_result)
        if passed:
            return (
                {
                    **lite_result,
                    "frame_status": "passed",
                    "frame_rejection_reason": None,
                },
                aggregated_usage,
            )
        return (
            {
                **lite_result,
                "frame_status": "rejected",
                "frame_rejection_reason": reason,
            },
            aggregated_usage,
        )
    except Exception as exc:  # noqa: BLE001
        reason = full_error or str(exc)
        return (
            {
                **topic,
                "frame_status": "rejected",
                "frame_rejection_reason": "generation_failed",
                "status": "failed",
                "errors": (topic.get("errors") or []) + [f"Frame generation failed: {reason}"],
            },
            aggregated_usage,
        )


async def generate_frames(
    ext_client,
    int_client,
    topics: list[TopicPayload],
) -> tuple[list[TopicPayload], list[str], UsageSummary]:
    errors: list[str] = []
    usage: UsageSummary = {}

    if is_mock_mode():
        framed = []
        for t in topics:
            framed.append(
                {
                    **t,
                    "frame_tier": "full",
                    "frame": {
                        "hook": "MOCK: 先给一个反直觉钩子",
                        "outline": ["问题现象", "商业逻辑", "影响人群", "结论+免责声明"],
                        "cta": "转给家族群里关心药费的人",
                        "monetize_hook": "可引出相关课程/带货线索",
                        "platform_tips": "口语化，避免术语",
                    },
                }
            )
        return framed, errors, usage

    framed: list[TopicPayload] = []

    for idx, t in enumerate(topics):
        if idx > 0:
            await asyncio.sleep(2)
        try:
            frame_result, frame_usage = await _frame_topic(ext_client, int_client, t)
            framed.append(frame_result)
            usage = _merge_usage(usage, frame_usage)
            if frame_result.get("frame_status") == "rejected":
                err = f"Frame generation failed for {t.get('title')}: {frame_result.get('frame_rejection_reason')}"
                errors.append(err)
        except Exception as exc:  # noqa: BLE001
            err = f"Frame generation failed for {t.get('title')}: {exc}"
            errors.append(err)
            t = {
                **t,
                "frame_status": "rejected",
                "frame_rejection_reason": "generation_failed",
                "status": "failed",
                "errors": (t.get("errors") or []) + [err],
            }
            framed.append(t)

    return framed, errors, usage
