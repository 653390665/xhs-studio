from __future__ import annotations

import threading
from typing import Any

from backend.app.adapters.xhs.request_env import direct_xhs_request_env

# The XHS PC login flow is stateful: ``activate`` performs the webSsk
# handshake, the QR create call mints the login b1, the first anonymous poll
# and the ``webprofile`` report seed the gid/MNS state.  All of it lives on a
# single PcDeviceProfile, and the final confirm exchange must be signed with
# that same state.  Keeping the live XHSLoginApi instance per qr_id mirrors the
# browser (and the CLI's ``XHSPcAuth.from_qrcode_login``) instead of rebuilding
# a stateless client on every poll.
_LIVE_SESSIONS: dict[str, tuple[Any, dict[str, Any]]] = {}
_LIVE_LOCK = threading.RLock()


def _new_api(state: dict[str, Any] | None):
    from apis.xhs_pc_login_apis import XHSLoginApi

    state = state or {}
    return XHSLoginApi(
        local_storage=state.get("local_storage") or {},
        b1=state.get("b1") or "",
        dsl=state.get("dsl") or "",
        web_build=state.get("web_build") or "",
    )


def _state_of(api: Any) -> dict[str, Any]:
    return {
        "local_storage": dict(getattr(api, "local_storage", {}) or {}),
        "b1": str(getattr(api, "_login_b1", "") or ""),
        "dsl": str(getattr(api, "dsl", "") or ""),
        "web_build": str(getattr(api, "web_build", "") or ""),
    }


def _drop_live(key: str) -> None:
    with _LIVE_LOCK:
        entry = _LIVE_SESSIONS.pop(key, None)
    if entry is not None:
        try:
            entry[0].close()
        except Exception:
            pass


class XhsPcLoginAdapter:
    def create_qrcode(self) -> dict[str, Any]:
        with direct_xhs_request_env():
            api = _new_api(None)
            cookies = api.generate_init_cookies()
            success, message, payload = api.generate_qrcode(cookies)
            if not success or not payload:
                raise RuntimeError(message)
            cookies = payload["cookies"]
            # Browser order: create QR -> first anonymous poll -> webprofile.
            try:
                api.check_qrcode_status(payload["qr_id"], payload["code"], cookies)
            except Exception:
                pass
            api.ensure_webprofile(cookies)
            state = _state_of(api)
            with _LIVE_LOCK:
                _LIVE_SESSIONS[str(payload["qr_id"])] = (api, state)
        return {
            "cookies": cookies,
            "qr_id": payload["qr_id"],
            "code": payload["code"],
            "qr_url": payload["qr_url"],
            "state": state,
        }

    def _live_api(self, key: str, state: dict[str, Any] | None):
        with _LIVE_LOCK:
            entry = _LIVE_SESSIONS.get(key)
        if entry is not None:
            return entry[0]
        api = _new_api(state)
        with _LIVE_LOCK:
            _LIVE_SESSIONS[key] = (api, state or {})
        return api

    def check_qrcode_status(
        self,
        qr_id: str,
        code: str,
        cookies: dict[str, Any],
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = str(qr_id)
        from apis.xhs_pc_login_apis import XhsLoginBlocked

        with direct_xhs_request_env():
            api = self._live_api(key, state)
            try:
                success, message, updated_cookies = api.check_qrcode_status(qr_id, code, cookies)
            except XhsLoginBlocked as blocked:
                # Risk control refused the call. This is a terminal answer for
                # this QR, not a transient error to poll through: the exchange is
                # one-shot and the platform has already spent it.
                _drop_live(key)
                return {
                    "status": "blocked",
                    "cookies": cookies,
                    "state": state or {},
                    "blocked_status_code": blocked.status_code,
                }
            new_state = _state_of(api)
            with _LIVE_LOCK:
                _LIVE_SESSIONS[key] = (api, new_state)
        status = "confirmed" if success else "pending"
        if "过期" in message or "expired" in message.lower():
            status = "expired"
        if "确认" in message or "confirm" in message.lower():
            status = "scanned"
        if status == "expired":
            _drop_live(key)
        return {"status": status, "cookies": updated_cookies, "state": new_state}

    def release(self, qr_id: str | None) -> None:
        if qr_id:
            _drop_live(str(qr_id))

    def get_user_info(self, cookies: dict[str, Any]) -> dict[str, Any]:
        """Fetch the logged-in user, refusing anonymous sessions.

        ``/v2/user/me`` answers ``success: true`` for a visitor too: the body is
        ``{"user_id": "6ae0...", "guest": true, "xsec_token": "..."}`` with no
        nickname. Checking only ``success`` turns that into an account named ""
        with ``status="active"``, which then fails every real API call and looks
        like an expired login. The SDK's own ``qrcode_login`` rejects this case
        (``user_info.get('guest') is not False``); this adapter now matches it.
        """
        with direct_xhs_request_env():
            from apis.xhs_pc_login_apis import XHSLoginApi

            api = XHSLoginApi()
            success, data, _ = api.get_user_info(cookies)
        if not success:
            raise RuntimeError("Failed to fetch XHS user info")
        if (data or {}).get("guest") is not False:
            raise RuntimeError("小红书返回的是访客会话，登录没有真正完成，请重新扫码")
        return {
            "external_user_id": data.get("user_id", ""),
            "nickname": data.get("nickname", ""),
            "avatar_url": data.get("images") or data.get("imageb") or "",
            "profile": {
                "red_id": data.get("red_id") or data.get("redId") or "",
                "followers": data.get("fans") or data.get("followers") or data.get("follower_count"),
                "following": data.get("follows") or data.get("following") or data.get("following_count"),
                "likes": data.get("liked_count") or data.get("likes") or data.get("like_count"),
                "raw": data,
            },
        }

    def create_phone_session(self, phone: str) -> dict[str, Any]:
        with direct_xhs_request_env():
            api = _new_api(None)
            cookies = api.generate_init_cookies()
            # The SMS flow also requires the anonymous profile acceptance
            # before the code is sent (see XHSLoginApi.phone_login).
            api.ensure_webprofile(cookies)
            success, message, _ = api.send_phone_code(phone, cookies)
            if success:
                with _LIVE_LOCK:
                    _LIVE_SESSIONS["phone:" + str(phone)] = (api, _state_of(api))
            else:
                try:
                    api.close()
                except Exception:
                    pass
        if not success:
            raise RuntimeError(message)
        return {"cookies": cookies, "message": message or "sent", "state": _state_of(api)}

    def confirm_phone_login(
        self,
        phone: str,
        code: str,
        cookies: dict[str, Any],
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = "phone:" + str(phone)
        with direct_xhs_request_env():
            api = self._live_api(key, state)
            success, message, payload = api.login_by_phone(phone, code, cookies)
        _drop_live(key)
        if not success or not payload:
            raise RuntimeError(message)
        return {"status": "confirmed", "cookies": payload["cookies"]}
