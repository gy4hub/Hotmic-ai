from __future__ import annotations

import time

from core.config import FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_BASE_URL
from pipeline.utils import request_with_retry

_TOKEN_CACHE: dict[str, float | str | None] = {
    "token": None,
    "expires_at": 0.0,
}


def feishu_enabled() -> bool:
    return bool(FEISHU_APP_ID and FEISHU_APP_SECRET)


async def get_tenant_access_token(client) -> str:
    if not feishu_enabled():
        raise RuntimeError("Feishu credentials missing: FEISHU_APP_ID / FEISHU_APP_SECRET")

    now = time.time()
    cached_token = _TOKEN_CACHE.get("token")
    expires_at = float(_TOKEN_CACHE.get("expires_at") or 0.0)
    if cached_token and now < expires_at - 60:
        return str(cached_token)

    url = f"{FEISHU_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }
    resp = await request_with_retry(client, "POST", url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(
            f"Feishu token request failed: code={data.get('code')} msg={data.get('msg')}"
        )

    token = data.get("tenant_access_token")
    expire_seconds = data.get("expire", 7200)
    if not token:
        raise RuntimeError("Feishu token request succeeded without tenant_access_token")

    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + int(expire_seconds)
    return str(token)
