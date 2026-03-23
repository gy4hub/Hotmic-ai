import asyncio
from typing import Any
from config import MAX_RETRIES, RETRY_BASE_SLEEP


async def request_with_retry(client, method: str, url: str, **kwargs):
    max_retries = kwargs.pop("max_retries", MAX_RETRIES)
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code in {408, 429} or resp.status_code >= 500:
                resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= max_retries:
                break
            await asyncio.sleep(RETRY_BASE_SLEEP * (2**attempt))
    if last_exc:
        raise last_exc
    raise RuntimeError("request_with_retry failed without exception")


def safe_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
