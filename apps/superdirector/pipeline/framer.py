import json
import asyncio
from pathlib import Path
from config import (
    GEMINI_API_KEY,
    GEMINI_FLASH_MODEL,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_MODEL,
    is_mock_mode,
)
from pipeline.utils import request_with_retry
from pipeline.types import TopicPayload, UsageSummary

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _prompt_from_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _prompt_path(platform: str) -> str:
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


async def _frame_with_qwen(int_client, topic: TopicPayload) -> tuple[TopicPayload, UsageSummary]:
    platform = topic.get("platform_priority") or "douyin"
    prompt = _prompt_from_file(_prompt_path(platform))

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
        {**topic, "frame": frame},
        _usage_summary("qwen", QWEN_MODEL, "chat.completions", data.get("usage", {})),
    )


async def _frame_with_gemini(ext_client, topic: TopicPayload) -> tuple[TopicPayload, UsageSummary]:
    platform = topic.get("platform_priority") or "douyin"
    prompt = _prompt_from_file(_prompt_path(platform))

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
        {**topic, "frame": frame},
        _usage_summary(
            "google",
            GEMINI_FLASH_MODEL,
            "generateContent",
            data.get("usageMetadata", {}),
        ),
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
            if QWEN_API_KEY:
                frame_result, frame_usage = await _frame_with_qwen(int_client, t)
            else:
                frame_result, frame_usage = await _frame_with_gemini(ext_client, t)
            framed.append(frame_result)
            if frame_usage:
                usage["provider"] = frame_usage.get("provider")
                usage["model"] = frame_usage.get("model")
                usage["endpoint"] = frame_usage.get("endpoint")
                usage["input_tokens"] = usage.get("input_tokens", 0) + (
                    frame_usage.get("input_tokens") or 0
                )
                usage["output_tokens"] = usage.get("output_tokens", 0) + (
                    frame_usage.get("output_tokens") or 0
                )
        except Exception as exc:  # noqa: BLE001
            err = f"Frame generation failed for {t.get('title')}: {exc}"
            errors.append(err)
            t = {**t, "status": "failed", "errors": (t.get("errors") or []) + [err]}
            framed.append(t)

    return framed, errors, usage
