import asyncio

from tools import wewe_monitor


class DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


def test_parse_account_payload_marks_relogin_when_invalid():
    result = wewe_monitor._parse_account_payload(
        {
            "items": [
                {"id": "1", "status": 1},
                {"id": "2", "status": 0},
                {"id": "3", "status": 2},
            ],
            "blocks": ["4"],
        }
    )

    assert result["account_total"] == 3
    assert result["account_enabled"] == 1
    assert result["account_invalid"] == 1
    assert result["account_disabled"] == 1
    assert result["account_blocked"] == 1
    assert result["needs_relogin"] is True


def test_get_wewe_health_handles_auth_error(monkeypatch):
    async def fake_request_with_retry(_client, _method, _url, **_kwargs):
        return DummyResponse(
            [
                {
                    "error": {
                        "message": "authCode不正确！",
                        "data": {"httpStatus": 401},
                    }
                }
            ]
        )

    monkeypatch.setattr(wewe_monitor, "WEWE_BASE_URL", "http://wewe.local:4000")
    monkeypatch.setattr(wewe_monitor, "WEWE_AUTH_CODE", None)
    monkeypatch.setattr(wewe_monitor, "request_with_retry", fake_request_with_retry)

    result = asyncio.run(wewe_monitor.get_wewe_health(object()))

    assert result["reachable"] is True
    assert result["needs_auth"] is True
    assert result["message"] == "authCode不正确！"


def test_create_wewe_login_qr_returns_scan_url(monkeypatch):
    async def fake_request_with_retry(_client, _method, _url, **_kwargs):
        return DummyResponse(
            [
                {
                    "result": {
                        "data": {
                            "uuid": "uuid-123",
                            "scanUrl": "https://open.weixin.qq.com/connect/confirm?uuid=uuid-123",
                        }
                    }
                }
            ]
        )

    monkeypatch.setattr(wewe_monitor, "WEWE_BASE_URL", "http://wewe.local:4000")
    monkeypatch.setattr(wewe_monitor, "WEWE_AUTH_CODE", "secret")
    monkeypatch.setattr(wewe_monitor, "request_with_retry", fake_request_with_retry)

    result = asyncio.run(wewe_monitor.create_wewe_login_qr(object()))

    assert result["created"] is True
    assert result["uuid"] == "uuid-123"
    assert result["scan_url"].startswith("https://open.weixin.qq.com/")
    assert "<svg" in result["qr_svg"]


def test_get_wewe_login_result_parses_authenticated(monkeypatch):
    class DummyClient:
        async def request(self, _method, _url, **_kwargs):
            return DummyResponse(
                {
                    "vid": 123,
                    "token": "token-abc",
                    "username": "tester",
                }
            )

    monkeypatch.setattr(wewe_monitor, "WEWE_PLATFORM_URL", "http://weread.local")

    result = asyncio.run(wewe_monitor.get_wewe_login_result(DummyClient(), "uuid-123"))

    assert result["authenticated"] is True
    assert result["payload"]["username"] == "tester"


def test_add_wewe_account_posts_payload(monkeypatch):
    captured = {}

    async def fake_request_with_retry(_client, method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["body"] = kwargs.get("content", b"").decode("utf-8")
        return DummyResponse(
            [
                {
                    "result": {
                        "data": {
                            "id": "123",
                            "name": "tester",
                            "status": 1,
                        }
                    }
                }
            ]
        )

    monkeypatch.setattr(wewe_monitor, "WEWE_BASE_URL", "http://wewe.local:4000")
    monkeypatch.setattr(wewe_monitor, "WEWE_AUTH_CODE", "secret")
    monkeypatch.setattr(wewe_monitor, "request_with_retry", fake_request_with_retry)

    result = asyncio.run(
        wewe_monitor.add_wewe_account(
            object(),
            account_id="123",
            token="token-abc",
            name="tester",
        )
    )

    assert result["added"] is True
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/trpc/account.add")
    assert '"id": "123"' in captured["body"]
    assert '"json"' not in captured["body"]


def test_get_wewe_login_result_surfaces_platform_message(monkeypatch):
    class DummyClient:
        async def request(self, _method, _url, **_kwargs):
            return DummyResponse({"message": "Login failed: 402", "statusCode": 500}, status_code=500)

    monkeypatch.setattr(wewe_monitor, "WEWE_PLATFORM_URL", "http://weread.local")

    result = asyncio.run(wewe_monitor.get_wewe_login_result(DummyClient(), "uuid-123"))

    assert result["authenticated"] is False
    assert "Login failed: 402" in result["message"]
    assert result["error_code"] == 500


def test_await_wewe_login_and_add_completes(monkeypatch):
    async def fake_get_wewe_login_result(_client, _uuid):
        return {
            "authenticated": True,
            "payload": {"vid": 123, "token": "token-abc", "username": "tester"},
        }

    async def fake_add_wewe_account(_client, *, account_id, token, name):
        return {
            "added": True,
            "account": {"id": account_id, "token": token, "name": name},
        }

    health_checks = {"count": 0}

    async def fake_get_wewe_health(_client):
        health_checks["count"] += 1
        return {
            "account_enabled": 1,
            "needs_relogin": False,
            "message": "WeWe-RSS 账号状态正常。",
        }

    monkeypatch.setattr(wewe_monitor, "get_wewe_login_result", fake_get_wewe_login_result)
    monkeypatch.setattr(wewe_monitor, "add_wewe_account", fake_add_wewe_account)
    monkeypatch.setattr(wewe_monitor, "get_wewe_health", fake_get_wewe_health)

    result = asyncio.run(wewe_monitor.await_wewe_login_and_add(object(), "uuid-123"))

    assert result["authenticated"] is True
    assert result["account_add"]["added"] is True
    assert result["account_add"]["account"]["id"] == "123"
    assert health_checks["count"] >= 1


def test_await_wewe_login_and_add_waits_for_healthy_account(monkeypatch):
    async def fake_get_wewe_login_result(_client, _uuid):
        return {
            "authenticated": True,
            "payload": {"vid": 123, "token": "token-abc", "username": "tester"},
        }

    async def fake_add_wewe_account(_client, *, account_id, token, name):
        return {
            "added": True,
            "account": {"id": account_id, "token": token, "name": name},
        }

    async def fake_get_wewe_health(_client):
        return {
            "account_enabled": 0,
            "needs_relogin": True,
            "message": "WeReadError401",
        }

    monkeypatch.setattr(wewe_monitor, "get_wewe_login_result", fake_get_wewe_login_result)
    monkeypatch.setattr(wewe_monitor, "add_wewe_account", fake_add_wewe_account)
    monkeypatch.setattr(wewe_monitor, "get_wewe_health", fake_get_wewe_health)

    result = asyncio.run(
        wewe_monitor.await_wewe_login_and_add(
            object(),
            "uuid-123",
            timeout_seconds=1,
            poll_interval=1,
            verify_timeout_seconds=1,
        )
    )

    assert result["authenticated"] is False
    assert result["message"] == "WeReadError401"
