"""The login poll answered 500 for a whole session. Why.

A real scan produced this sequence:

1. ``POST /api/qrcode/userinfo`` returned ``codeStatus: 2`` — the user *had*
   scanned and confirmed.
2. The flow then called the one-shot exchange
   ``GET /api/sns/web/v1/login/qrcode/status`` and got **HTTP 471** with
   ``{"code": 0, "success": true, "msg": "成功", "data": {}}``.
3. No code path looked at ``resp.status_code``. The body says success, the data
   is empty, so ``_login_by_qrcode_status`` raised
   ``RuntimeError(res.get('msg'))`` — i.e. ``RuntimeError: 成功``. An error whose
   message is "successful".
4. Nothing caught it, so ``GET /api/xhs/login-sessions/{id}`` returned 500
   "Internal Server Error", the session stayed ``scanned``, and the UI retried
   the already-spent exchange every two seconds for as long as the panel stayed
   open.

Three separate defects:

* the block was invisible (HTTP status ignored),
* the failure was unactionable (500 instead of "refused, refresh the QR"),
* the failure was non-terminal (retry storm against risk control).

A fourth test covers a near-miss found on the way: ``/v2/user/me`` answers
``success: true`` for an anonymous visitor, so a login that never completed would
have created an account with an empty nickname and ``status="active"``.
"""

from __future__ import annotations

import pytest

from apis.xhs_pc_login_apis import XHSLoginApi, XhsLoginBlocked


class FakeResponse:
    """Just enough of a requests response for the SDK's parsing code."""

    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self) -> dict:
        return self._payload


# The exact 471 body the platform sent: success true, data empty.
BLOCKED_BODY = {"code": 0, "success": True, "msg": "成功", "data": {}}


def _api_with(monkeypatch, response: FakeResponse) -> XHSLoginApi:
    """An API object wired to a canned HTTP response.

    The signing and wire-header machinery is stubbed out: this file tests what
    the code does with a response, not how it is signed. ``build_pc_login_headers``
    is a module-level import in the SDK, so it is patched there.
    """
    import apis.xhs_pc_login_apis as sdk

    api = XHSLoginApi()
    monkeypatch.setattr(
        api, "_signed_request_params", lambda *args, **kwargs: ({"cookie": "a1=x"}, {})
    )
    monkeypatch.setattr(api, "_merge_response_cookies", lambda *args, **kwargs: None)
    monkeypatch.setattr(api, "_cookies_for_url", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        sdk, "build_pc_login_headers", lambda headers, *args, **kwargs: headers
    )
    # The success path persists cookies into the device profile; a stub stands in
    # for it so the assertion is about the session value, not the profile object.
    monkeypatch.setattr(
        api, "profile", type("Profile", (), {"update_cookies": lambda self, c: None})(),
        raising=False,
    )
    monkeypatch.setattr(api.http, "get", lambda *args, **kwargs: response)
    monkeypatch.setattr(api.http, "post", lambda *args, **kwargs: response)
    return api


# --- the exchange that raised `RuntimeError: 成功` ---------------------------


def test_blocked_exchange_raises_instead_of_reporting_success(monkeypatch):
    """The error message used to be the platform's own word: "成功"."""
    api = _api_with(monkeypatch, FakeResponse(471, BLOCKED_BODY))

    with pytest.raises(XhsLoginBlocked) as caught:
        api._login_by_qrcode_status(
            "qr-1", "code-1", {"a1": "x", "web_session": "visitor"}
        )

    assert caught.value.status_code == 471
    # The old code raised RuntimeError("成功"), so the UI could only say
    # "轮询登录状态失败" with no idea what happened.
    assert "471" in str(caught.value)


def test_exchange_still_works_when_the_platform_answers_normally(monkeypatch):
    """The guard must not break the success path."""
    body = {
        "code": 0,
        "success": True,
        "msg": "成功",
        "data": {"code_status": 2, "login_info": {"session": "real-session"}},
    }
    api = _api_with(monkeypatch, FakeResponse(200, body))
    cookies = {"a1": "x", "web_session": "visitor"}

    result = api._login_by_qrcode_status("qr-1", "code-1", cookies)

    assert result["web_session"] == "real-session"


def test_exchange_rejects_a_200_that_still_lacks_a_session(monkeypatch):
    """A silent 200 without login_info must not pass as logged in."""
    body = {"code": 0, "success": True, "msg": "成功", "data": {"code_status": 2}}
    api = _api_with(monkeypatch, FakeResponse(200, body))
    cookies = {"a1": "x", "web_session": "visitor-session"}

    with pytest.raises(RuntimeError) as caught:
        api._login_by_qrcode_status("qr-1", "code-1", cookies)

    assert "web_session" in str(caught.value)


def test_poll_reports_a_block_instead_of_a_missing_field(monkeypatch):
    """``codeStatus`` is absent in the block body; that read as our own bug."""
    api = _api_with(monkeypatch, FakeResponse(471, BLOCKED_BODY))

    with pytest.raises(XhsLoginBlocked):
        api.check_qrcode_status(
            "qr-1", "code-1", {"a1": "x", "web_session": "visitor"}
        )


def test_poll_maps_pending_status(monkeypatch):
    body = {"code": 0, "success": True, "msg": "成功", "data": {"codeStatus": 0}}
    api = _api_with(monkeypatch, FakeResponse(200, body))

    success, message, _ = api.check_qrcode_status("qr-1", "code-1", {"a1": "x"})

    assert success is False
    assert message == "请扫描二维码"


def test_poll_maps_expired_status(monkeypatch):
    body = {"code": 0, "success": True, "msg": "成功", "data": {"codeStatus": 3}}
    api = _api_with(monkeypatch, FakeResponse(200, body))

    success, message, _ = api.check_qrcode_status("qr-1", "code-1", {"a1": "x"})

    assert success is False
    assert message == "二维码已过期"


# --- the anonymous-session near miss ---------------------------------------


def test_adapter_rejects_a_guest_session(monkeypatch):
    """``success: true`` is not proof of login; ``guest`` is.

    The real response for an unauthenticated session is
    ``{"user_id": "...", "guest": true, "xsec_token": "..."}`` with no nickname.
    The adapter used to accept it, which would have written
    ``nickname=""`` and ``status="active"`` — an account that looks connected
    and fails every subsequent call.
    """
    import apis.xhs_pc_login_apis as sdk
    from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter

    class GuestApi:
        def __init__(self, *args, **kwargs):
            pass

        def get_user_info(self, cookies):
            return True, {"user_id": "guest-id", "guest": True}, cookies

    monkeypatch.setattr(sdk, "XHSLoginApi", GuestApi)

    adapter = XhsPcLoginAdapter()
    with pytest.raises(RuntimeError) as caught:
        adapter.get_user_info({"a1": "x", "web_session": "visitor"})

    assert "访客" in str(caught.value)


def test_adapter_accepts_a_real_session(monkeypatch):
    """The guard must not reject a genuine login."""
    import apis.xhs_pc_login_apis as sdk
    from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter

    class RealApi:
        def __init__(self, *args, **kwargs):
            pass

        def get_user_info(self, cookies):
            return (
                True,
                {"user_id": "real-id", "guest": False, "nickname": "Neo阿桑"},
                cookies,
            )

    monkeypatch.setattr(sdk, "XHSLoginApi", RealApi)

    adapter = XhsPcLoginAdapter()
    info = adapter.get_user_info({"a1": "x", "web_session": "real"})

    assert info["external_user_id"] == "real-id"
    assert info["nickname"] == "Neo阿桑"
