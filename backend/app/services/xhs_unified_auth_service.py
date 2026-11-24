"""Unified XHS auth: one PC login also unlocks the Creator (创作者中心) view.

Upstream Spider_XHS v5.0.0 added ``xhs_utils.xhs_auth.XHSUnifiedAuth``: the PC
and Creator sites share the same session cookies, so a single PC cookie/login
can lazily derive a working ``XHSCreatorAuth``. This module exposes that bridge
to the API layer as a **read-only capability check** — it never stores anything
and never changes the existing separate login flows.
"""

from __future__ import annotations

from typing import Any

from backend.app.adapters.xhs.request_env import direct_xhs_request_env

CREATOR_PROBE_KEYWORD = "小红书"


def check_creator_bridge(cookies: str, keyword: str = CREATOR_PROBE_KEYWORD) -> dict[str, Any]:
    """Verify that PC cookies can drive the Creator APIs.

    ``keyword`` is only a connectivity probe (any public topic works); it is not
    related to the account's niche. Returns ``{ok, keyword, creator_build,
    sample_topics, error}``.
    """
    keyword = (keyword or CREATOR_PROBE_KEYWORD).strip() or CREATOR_PROBE_KEYWORD
    if not cookies or not cookies.strip():
        return {
            "ok": False,
            "keyword": keyword,
            "creator_build": "",
            "sample_topics": [],
            "error": "账号没有可用的 Cookie",
        }

    try:
        from apis.xhs_creator_apis import XHS_Creator_Apis
        from xhs_utils.xhs_auth import XHSUnifiedAuth
    except Exception as error:  # noqa: BLE001 - SDK missing/renamed
        return {
            "ok": False,
            "keyword": keyword,
            "creator_build": "",
            "sample_topics": [],
            "error": f"SDK 不可用：{error}",
        }

    creator_build = ""
    try:
        from apis import xhs_creator_login_apis

        creator_build = str(getattr(xhs_creator_login_apis, "CREATOR_WEB_BUILD", "") or "")
    except Exception:  # noqa: BLE001
        creator_build = ""

    try:
        with XHSUnifiedAuth.from_cookie(cookies) as unified:
            creator = unified.creator
            with direct_xhs_request_env():
                success, message, payload = XHS_Creator_Apis(creator).get_topic(keyword=keyword)
    except Exception as error:  # noqa: BLE001 - surface a readable reason
        return {
            "ok": False,
            "keyword": keyword,
            "creator_build": creator_build,
            "sample_topics": [],
            "error": f"{type(error).__name__}: {error}",
        }

    if not success:
        return {
            "ok": False,
            "keyword": keyword,
            "creator_build": creator_build,
            "sample_topics": [],
            "error": str(message or "创作者中心接口返回失败"),
        }

    topics: list[str] = []
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        for item in data.get("topic_info_dtos") or data.get("topics") or []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("title")
                if name:
                    topics.append(str(name))
    return {
        "ok": True,
        "keyword": keyword,
        "creator_build": creator_build,
        "sample_topics": topics[:5],
        "error": "",
    }


__all__ = ["CREATOR_PROBE_KEYWORD", "check_creator_bridge"]
