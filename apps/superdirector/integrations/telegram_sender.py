from __future__ import annotations

from typing import Any

from core.config import HTTPS_PROXY, HTTP_PROXY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


async def send_telegram(client, text: str, chat_id: str | None = None, parse_mode: str = "HTML") -> dict[str, Any]:
    bot_token = str(TELEGRAM_BOT_TOKEN or "").strip()
    target_chat_id = str(chat_id or TELEGRAM_CHAT_ID or "").strip()
    if not bot_token or not target_chat_id:
        raise RuntimeError("Telegram delivery target is not configured")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = await client.post(
        url,
        json={
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": parse_mode,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


async def send_casey_message(client, text: str) -> dict[str, Any]:
    return await send_telegram(client, text)


async def send_casey_photo(client, image_bytes: bytes, caption: str | None = None) -> dict[str, Any]:
    bot_token = str(TELEGRAM_BOT_TOKEN or "").strip()
    target_chat_id = str(TELEGRAM_CHAT_ID or "").strip()
    if not bot_token or not target_chat_id:
        raise RuntimeError("Telegram delivery target is not configured")
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    resp = await client.post(
        url,
        data={"chat_id": target_chat_id, "caption": caption or ""},
        files={"photo": ("qr.png", image_bytes, "image/png")},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def proxy_hint() -> str | None:
    return HTTP_PROXY or HTTPS_PROXY
