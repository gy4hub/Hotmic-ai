from __future__ import annotations

import asyncio
import io
import json
from typing import Any

import qrcode
import qrcode.image.svg

from core.config import WEWE_AUTH_CODE, WEWE_BASE_URL, WEWE_PLATFORM_URL
from pipeline.utils import request_with_retry


def _parse_account_payload(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items") or []
    blocks = payload.get("blocks") or []

    total = len(items)
    enabled = sum(1 for item in items if item.get("status") == 1)
    invalid = sum(1 for item in items if item.get("status") == 0)
    disabled = sum(1 for item in items if item.get("status") == 2)
    blocked = len(blocks)

    needs_relogin = invalid > 0 or enabled == 0
    if enabled == 0:
        message = "WeWe-RSS 当前没有可用读书账号，需要重新扫码登录。"
    elif invalid > 0:
        message = f"WeWe-RSS 有 {invalid} 个账号失效，建议尽快重新登录。"
    elif blocked > 0:
        message = f"WeWe-RSS 有 {blocked} 个账号今日小黑屋，建议降低抓取频率。"
    else:
        message = "WeWe-RSS 账号状态正常。"

    return {
        "account_total": total,
        "account_enabled": enabled,
        "account_invalid": invalid,
        "account_disabled": disabled,
        "account_blocked": blocked,
        "needs_relogin": needs_relogin,
        "message": message,
        "items": items,
        "blocks": blocks,
    }


def _extract_trpc_error(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        error = payload[0].get("error")
        if isinstance(error, dict):
            return error
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return error
    return None


def _humanize_wewe_login_error(message: str) -> str:
    text = (message or "").strip()
    if text == "Login failed: 402":
        return "Login failed: 402（通常表示二维码已过期，或本次扫码后没有在微信里完成确认）"
    return text


async def get_wewe_health(int_client) -> dict[str, Any]:
    if not WEWE_BASE_URL:
        return {
            "enabled": False,
            "reachable": False,
            "auth_configured": False,
            "message": "WEWE_BASE_URL 未配置，无法检查账号状态。",
        }

    url = f"{WEWE_BASE_URL.rstrip('/')}/trpc/account.list"
    params = {
        "batch": "1",
        "input": json.dumps({"0": {}}, ensure_ascii=False, separators=(",", ":")),
    }
    headers = {}
    if WEWE_AUTH_CODE:
        headers["Authorization"] = WEWE_AUTH_CODE

    try:
        resp = await request_with_retry(int_client, "GET", url, params=params, headers=headers)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": True,
            "reachable": False,
            "auth_configured": bool(WEWE_AUTH_CODE),
            "message": f"WeWe-RSS 状态检查失败: {exc}",
        }

    if getattr(resp, "status_code", 200) >= 500:
        return {
            "enabled": True,
            "reachable": False,
            "auth_configured": bool(WEWE_AUTH_CODE),
            "message": f"WeWe-RSS 服务异常: HTTP {resp.status_code}",
        }

    error = _extract_trpc_error(data)
    if error:
        return {
            "enabled": True,
            "reachable": True,
            "auth_configured": bool(WEWE_AUTH_CODE),
            "message": error.get("message") or "WeWe-RSS 返回错误",
            "error_code": error.get("data", {}).get("httpStatus"),
            "needs_auth": error.get("data", {}).get("httpStatus") == 401,
        }

    payload = data[0].get("result", {}).get("data", {}) if isinstance(data, list) and data else {}

    parsed = _parse_account_payload(payload)
    return {
        "enabled": True,
        "reachable": True,
        "auth_configured": bool(WEWE_AUTH_CODE),
        **parsed,
    }


async def create_wewe_login_qr(int_client) -> dict[str, Any]:
    if not WEWE_BASE_URL:
        return {
            "enabled": False,
            "message": "WEWE_BASE_URL 未配置，无法生成登录二维码。",
        }
    if not WEWE_AUTH_CODE:
        return {
            "enabled": True,
            "auth_configured": False,
            "message": "WEWE_AUTH_CODE 未配置，无法调用登录接口。",
        }

    url = f"{WEWE_BASE_URL.rstrip('/')}/trpc/platform.createLoginUrl"
    headers = {
        "Authorization": WEWE_AUTH_CODE,
        "content-type": "application/json",
    }
    payload = {"0": None}

    try:
        resp = await request_with_retry(
            int_client,
            "POST",
            url,
            params={"batch": "1"},
            headers=headers,
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": True,
            "auth_configured": True,
            "created": False,
            "message": f"WeWe-RSS 创建登录二维码失败: {exc}",
        }

    error = _extract_trpc_error(data)
    if error:
        return {
            "enabled": True,
            "auth_configured": True,
            "created": False,
            "message": error.get("message") or "WeWe-RSS 返回错误",
            "error_code": error.get("data", {}).get("httpStatus"),
        }

    payload = data[0].get("result", {}).get("data", {}) if isinstance(data, list) and data else {}
    scan_url = payload.get("scanUrl")
    uuid = payload.get("uuid")
    qr_svg = _build_qr_svg(scan_url) if scan_url else None
    return {
        "enabled": True,
        "auth_configured": True,
        "created": bool(scan_url and uuid),
        "uuid": uuid,
        "scan_url": scan_url,
        "qr_svg": qr_svg,
    }


async def get_wewe_login_result(int_client, uuid: str) -> dict[str, Any]:
    if not uuid:
        return {
            "enabled": True,
            "auth_configured": bool(WEWE_AUTH_CODE),
            "message": "缺少登录二维码 uuid，无法检查登录状态。",
            "authenticated": False,
        }

    # Query the underlying Weread login endpoint directly so we can surface
    # the real failure message instead of tRPC's generic 500 wrapper.
    url = f"{WEWE_PLATFORM_URL.rstrip('/')}/api/v2/login/platform/{uuid}"

    try:
        resp = await int_client.request("GET", url)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": True,
            "auth_configured": bool(WEWE_AUTH_CODE),
            "message": f"WeWe-RSS 查询登录状态失败: {exc}",
            "authenticated": False,
        }

    if getattr(resp, "status_code", 200) >= 400:
        message = ""
        if isinstance(data, dict):
            message = str(data.get("message") or "").strip()
        if not message:
            message = f"WeWe-RSS 登录检查失败: HTTP {resp.status_code}"
        message = _humanize_wewe_login_error(message)
        return {
            "enabled": True,
            "auth_configured": bool(WEWE_AUTH_CODE),
            "message": message,
            "error_code": resp.status_code,
            "authenticated": False,
        }

    payload = data if isinstance(data, dict) else {}
    return {
        "enabled": True,
        "auth_configured": bool(WEWE_AUTH_CODE),
        "authenticated": bool(payload.get("vid") and payload.get("token")),
        "payload": payload,
    }


async def await_wewe_login_and_add(
    int_client,
    uuid: str,
    *,
    timeout_seconds: int = 90,
    poll_interval: int = 3,
    verify_timeout_seconds: int = 20,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + max(timeout_seconds, 1)
    last_result: dict[str, Any] | None = None

    while asyncio.get_running_loop().time() < deadline:
        result = await get_wewe_login_result(int_client, uuid)
        last_result = result
        if result.get("authenticated"):
            payload = result.get("payload") or {}
            account_id = str(payload.get("vid") or "")
            account_name = str(payload.get("username") or f"weread-{payload.get('vid')}")
            added = await add_wewe_account(
                int_client,
                account_id=account_id,
                token=payload.get("token"),
                name=account_name,
            )
            if added.get("added") is not True:
                return {
                    "authenticated": False,
                    "uuid": uuid,
                    "account_id": account_id,
                    "account_name": account_name,
                    "login_result": result,
                    "account_add": added,
                    "message": str(added.get("message") or "WeWe-RSS 账号写回失败。"),
                }

            # Do not declare success until the account is actually usable.
            verification_deadline = (
                asyncio.get_running_loop().time() + max(verify_timeout_seconds, 1)
            )
            last_health: dict[str, Any] | None = None
            while asyncio.get_running_loop().time() < verification_deadline:
                health = await get_wewe_health(int_client)
                last_health = health
                if health.get("account_enabled", 0) > 0 and not health.get("needs_relogin"):
                    return {
                        "authenticated": True,
                        "uuid": uuid,
                        "account_id": account_id,
                        "account_name": account_name,
                        "login_result": result,
                        "account_add": added,
                        "health": health,
                    }
                await asyncio.sleep(2)

            return {
                "authenticated": False,
                "uuid": uuid,
                "account_id": account_id,
                "account_name": account_name,
                "login_result": result,
                "account_add": added,
                "health": last_health,
                "message": str(
                    (last_health or {}).get("message")
                    or "扫码后账号仍未恢复可用，可能是微信侧确认未完成或登录态失效。"
                ),
            }
        await asyncio.sleep(max(poll_interval, 1))

    return {
        "authenticated": False,
        "uuid": uuid,
        "timeout": True,
        "login_result": last_result,
    }


async def add_wewe_account(int_client, *, account_id: str, token: str, name: str) -> dict[str, Any]:
    if not WEWE_BASE_URL:
        return {
            "enabled": False,
            "message": "WEWE_BASE_URL 未配置，无法写入账号。",
        }
    if not WEWE_AUTH_CODE:
        return {
            "enabled": True,
            "auth_configured": False,
            "message": "WEWE_AUTH_CODE 未配置，无法写入账号。",
        }

    url = f"{WEWE_BASE_URL.rstrip('/')}/trpc/account.add"
    headers = {
        "Authorization": WEWE_AUTH_CODE,
        "content-type": "application/json",
    }
    payload = {
        "0": {
            "id": account_id,
            "token": token,
            "name": name,
            "status": 1,
        }
    }

    try:
        resp = await request_with_retry(
            int_client,
            "POST",
            url,
            params={"batch": "1"},
            headers=headers,
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": True,
            "auth_configured": True,
            "added": False,
            "message": f"WeWe-RSS 写入账号失败: {exc}",
        }

    error = _extract_trpc_error(data)
    if error:
        return {
            "enabled": True,
            "auth_configured": True,
            "added": False,
            "message": error.get("message") or "WeWe-RSS 返回错误",
            "error_code": error.get("data", {}).get("httpStatus"),
        }

    result = data[0].get("result", {}).get("data", {}) if isinstance(data, list) and data else {}
    return {
        "enabled": True,
        "auth_configured": True,
        "added": True,
        "account": result,
    }


def _build_qr_svg(value: str) -> str:
    if not value:
        return ""
    image = qrcode.make(value, image_factory=qrcode.image.svg.SvgImage)
    return image.to_string(encoding="unicode")


def build_wewe_scan_url(uuid: str) -> str:
    uuid = (uuid or "").strip()
    if not uuid:
        return ""
    return f"https://open.weixin.qq.com/connect/confirm?uuid={uuid}"


def build_wewe_qr_png(value: str) -> bytes:
    if not value:
        return b""
    qr = qrcode.QRCode(border=2, box_size=12)
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
