from __future__ import annotations

import hashlib
from typing import Any

from backend.app.adapters.xhs.request_env import direct_xhs_request_env


class XhsAuthExpired(RuntimeError):
    """The stored XHS cookies are no longer valid (needs a fresh login)."""


class XhsPcApiAdapter:
    """XHS PC adapter with a crawl budget enforced at this layer.

    The budget used to live only in the API handler (``api/corpus.py``), which
    meant anything calling the adapter directly — a script, a background job, a
    future feature — had no pacing at all. That is how a 294-post body crawl ran
    at ~29 requests/minute against a documented limit of 5 and got the account
    flagged: the guard was never consulted, because the guard was on the other
    side of the call.

    Enforcing here means every path pays the same price: UI, scheduler, agent and
    ad-hoc scripts. It cannot be bypassed by forgetting to call it.

    The bucket key is the cookie fingerprint, not ``account_id``: the adapter does
    not know the account, and "which login is being used" is what determines the
    platform-side risk anyway.
    """

    def __init__(self, cookies: str) -> None:
        self.cookies = cookies
        self._budget_key = "cookie:" + hashlib.sha256(
            (cookies or "").encode("utf-8")
        ).hexdigest()[:16]
        # Set only by ``open_paced_api()``, which is what the adapter's own
        # methods use. Reaching for it directly is how the 2026-10-28 incident
        # happened.
        self._paced_api_handle = None

    def _pace(self, action: str) -> None:
        """Block until this action fits the budget, or raise ``CrawlThrottled``."""
        from backend.app.services.crawl_guard import get_crawl_guard

        get_crawl_guard().acquire(self._budget_key, action)

    def _call_with_backoff(self, fn, action: str):
        """跑一次平台调用；如果被平台限流（429/461），退避后重试。

        为什么放在 adapter 里而不是每个调用方：
        当前 ``apis/`` 是「直发无重试」版本（上游原版有 _executor.py 的
        0.8/2.0/5.0 退避，这一版没有）。所以一次瞬时限流会直接变成
        用户可见的「采集失败」，而实际上等 30 秒再试就能成功。

        放在这里有两个好处：
          · 所有调用方（UI / 调度器 / agent / 脚本）自动获得重试；
          · 重试**不动** crawl_guard 的预算 —— 每次重试仍然走 _pace，
            所以「退避」和「限速」是两套独立的防线，不是互相抵消。

        只重试限流，不重试 404/已删除/空正文 —— 那些重试 3 次只是浪费时间。
        """
        from backend.app.services.crawl_guard import ThrottledRetry

        retry = ThrottledRetry()
        result = (False, "未执行", None)
        while retry.attempt():
            # 重试之前仍然要过一次预算：退避不等于可以不排队
            try:
                self._pace(action)
            except Exception:
                # 预算本身拒绝时不再重试，直接让上层看到限流原因
                raise
            with direct_xhs_request_env():
                result = fn()
            if not isinstance(result, tuple) or len(result) < 2:
                return result
            if result[0] or not ThrottledRetry.should_retry(str(result[1])):
                return result
        return result

    def _api(self):
        """Return the raw SDK client.

        Callers outside this class must not use this: it bypasses pacing and is
        the exact hole that got the account flagged. Use the public methods
        (``get_note_info``, ``get_user_notes``, …) or the HTTP API.

        When handed out via ``open_paced_api()`` the resulting object records
        usage so a guard test can tell a paced caller from an unguarded one.
        """
        from apis.xhs_pc_apis import XHS_Apis
        from xhs_utils.xhs_pc import XHSPcAuth

        try:
            auth = XHSPcAuth.from_cookie(self.cookies)
        except Exception as error:  # noqa: BLE001 - bootstrap failure means expired login
            message = str(error) or "登录态无效"
            raise XhsAuthExpired(
                f"小红书账号登录已过期，请到「账号」重新扫码/手机号登录后再试（{message}）"
            ) from error
        return XHS_Apis(auth)

    def search_note(
        self,
        keyword: str,
        page: int = 1,
        sort_type_choice: int = 0,
        note_type: int = 0,
        note_time: int = 0,
        note_range: int = 0,
        pos_distance: int = 0,
        geo: str = "",
    ) -> Any:
        return self._call_with_backoff(
            lambda: self._api().search_note(
                query=keyword,
                page=page,
                sort_type_choice=sort_type_choice,
                note_type=note_type,
                note_time=note_time,
                note_range=note_range,
                pos_distance=pos_distance,
                geo=geo,
            ),
            "search",
        )

    def get_note_info(self, url: str) -> Any:
        return self._call_with_backoff(
            lambda: self._api().get_note_info(url=url), "note_detail"
        )

    def get_note_comments(self, note_url: str) -> Any:
        try:
            return self._call_with_backoff(
                lambda: self._api().get_note_all_comment(url=note_url), "note_detail"
            )
        except Exception as error:  # noqa: BLE001 - surface instead of raising a 500
            return False, f"获取评论失败：{error}", None

    def get_user_notes(self, user_url: str) -> Any:
        return self._call_with_backoff(
            lambda: self._api().get_user_all_notes(user_url=user_url), "profile_page"
        )

    def get_user_notes_page(self, user_url: str, cursor: str = "") -> Any:
        from urllib.parse import parse_qs, urlparse

        parsed = urlparse(user_url)
        user_id = parsed.path.rstrip("/").split("/")[-1]
        params = parse_qs(parsed.query)
        xsec_token = (params.get("xsec_token") or [""])[0]
        xsec_source = (params.get("xsec_source") or ["pc_search"])[0]
        return self._call_with_backoff(
            lambda: self._api().get_user_note_info(
                user_id, cursor, xsec_token, xsec_source
            ),
            "profile_page",
        )

    def get_self_info(self) -> Any:
        with direct_xhs_request_env():
            success, message, res_json = self._api().get_user_me()
        payload = (res_json or {}).get("data") if isinstance(res_json, dict) else None
        if not success or not payload:
            raise RuntimeError(message or "XHS self profile refresh failed")
        return payload

    def get_user_info(self, user_id: str) -> Any:
        return self._call_with_backoff(
            lambda: self._api().get_user_info(user_id=user_id), "profile_page"
        )
