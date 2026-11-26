"""创作中心限速 + 429/461 退避重试 + 抖音节流。

2026-11-27 补的三块，之前都是空白：
  · creator_api_adapter 整个文件没有 pace（发布/上传裸调）
  · 抖音采集零节流（20 条清单连下 20 个视频）
  · apis 层无重试退避（一次瞬时限流 = 用户可见的失败）
"""

from __future__ import annotations

import inspect
import time

import pytest

from backend.app.services import crawl_guard as cg
from backend.app.services.crawl_guard import (
    ACTION_LIMITS,
    THROTTLE_BACKOFF,
    ThrottledRetry,
    call_with_backoff,
    looks_throttled,
)


# ---------------------------------------------------------------- 创作中心


def test_creator_actions_have_limits():
    for action in ("creator_publish", "creator_upload", "creator_meta"):
        assert action in ACTION_LIMITS, f"{action} 没有限额，发布链路就是裸的"
        assert 0 < ACTION_LIMITS[action] <= 10


def test_publish_is_the_strictest():
    """发布是最敏感的动作，限额必须比查询更严。"""
    assert ACTION_LIMITS["creator_publish"] < ACTION_LIMITS["creator_meta"]
    assert ACTION_LIMITS["creator_publish"] < ACTION_LIMITS["note_detail"]


def test_creator_adapter_paces_before_calling(monkeypatch):
    """创作中心的每个平台方法都必须先过预算。"""
    from backend.app.adapters.xhs import creator_api_adapter as mod

    adapter = mod.XhsCreatorApiAdapter("a1=abc; web_session=xyz")
    actions: list[str] = []

    class _FakeGuard:
        def acquire(self, key, action, **kwargs):
            actions.append(action)

    monkeypatch.setattr(cg, "get_crawl_guard", lambda: _FakeGuard())
    monkeypatch.setattr(adapter, "_api", lambda: (_ for _ in ()).throw(RuntimeError("x")))

    calls = {
        "creator_meta": lambda: adapter.get_topic("话题"),
        "creator_upload": lambda: adapter.upload_media(__file__, "image"),
        "creator_publish": lambda: adapter.post_note({"media_type": "video"}),
    }
    for expected, call in calls.items():
        with pytest.raises(Exception):
            call()
        assert expected in actions, f"{expected} 未经限速"


def test_creator_bucket_is_separate_from_pc():
    """创作中心和 PC 侧不能共用一个桶，否则查详情会把发布额度吃掉。"""
    from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter
    from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter

    cookies = "a1=abc; web_session=xyz"
    assert XhsCreatorApiAdapter(cookies)._budget_key.startswith("creator:")
    assert XhsPcApiAdapter(cookies)._budget_key.startswith("cookie:")


# ---------------------------------------------------------------- 退避重试


def test_throttle_hints_cover_429_and_461():
    assert looks_throttled("HTTP 429 Too Many Requests")
    assert looks_throttled("HTTP 461 risk control")
    assert looks_throttled("请求太频繁")
    assert not looks_throttled("404 not found")
    assert not looks_throttled("笔记已删除")


def test_backoff_is_not_a_fixed_interval():
    """退避的三档必须递增，且不能是同一个数。"""
    assert THROTTLE_BACKOFF == tuple(sorted(THROTTLE_BACKOFF))
    assert len(set(THROTTLE_BACKOFF)) == len(THROTTLE_BACKOFF)
    assert THROTTLE_BACKOFF[0] >= 5, "第一档至少 5 秒，太短等于立刻再撞一次"


def test_call_with_backoff_retries_throttled_then_succeeds():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            return (False, "HTTP 461 risk control", None)
        return (True, "ok", {"data": 1})

    ok, msg, payload = call_with_backoff(fn, backoff=(0.001, 0.001, 0.001))
    assert ok is True
    assert calls["n"] == 3
    assert payload == {"data": 1}


def test_call_with_backoff_does_not_retry_404():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return (False, "404 not found", None)

    ok, _msg, _payload = call_with_backoff(fn, backoff=(0.001, 0.001, 0.001))
    assert ok is False
    assert calls["n"] == 1, "404 重试 3 次只是浪费时间"


def test_call_with_backoff_gives_up_after_three():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return (False, "461", None)

    ok, _msg, _payload = call_with_backoff(fn, backoff=(0.001, 0.001, 0.001))
    assert ok is False
    assert calls["n"] == len(THROTTLE_BACKOFF), (
        "撞三次还继续试，是升级成设备级拦截的典型路径"
    )


def test_call_with_backoff_passes_success_through():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return (True, "ok", None)

    assert call_with_backoff(fn)[0] is True
    assert calls["n"] == 1


# ---------------------------------------------------------------- 抖音


def test_douyin_actions_have_limits():
    assert "douyin_download" in ACTION_LIMITS
    assert "douyin_discover" in ACTION_LIMITS
    # 主页 HTML 有风控校验页，必须比视频直链更慢
    assert ACTION_LIMITS["douyin_discover"] < ACTION_LIMITS["douyin_download"]


def test_douyin_run_loop_paces_between_works():
    """run_job 的作品循环里必须有 pace 调用。"""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "backend/app/services/douyin_extract_service.py"
    ).read_text(encoding="utf-8")
    assert "_pace_between_works(" in src, "作品之间没有节流"
    assert "douyin_download" in src
    assert "douyin_discover" in src


def test_douyin_pace_helper_never_raises():
    """抖音是长任务：限速被拒也不能让整个任务失败。"""
    from backend.app.services.douyin_extract_service import _pace_between_works

    # 不该抛异常，最多退化成一个短停
    started = time.monotonic()
    _pace_between_works(999999)
    elapsed = time.monotonic() - started
    assert elapsed < 60, "节流不该卡住这么久"


# ---------------------------------------------------------------- 封面下载


def test_media_asset_has_limit():
    assert "media_asset" in ACTION_LIMITS
    assert ACTION_LIMITS["media_asset"] <= 20


def test_asset_downloader_consults_guard(monkeypatch):
    from backend.app.services import asset_downloader as mod

    used: list[str] = []

    class _FakeGuard:
        def acquire(self, key, action, **kwargs):
            used.append(action)

    monkeypatch.setattr(cg, "get_crawl_guard", lambda: _FakeGuard())
    # 非法 URL 直接返回 None，但我们只关心它有没有先过预算
    mod.download_asset_to_local("not-a-url", 1, "image")
    assert used == [], "非 http URL 不该消耗预算"

    mod.download_asset_to_local("https://example.invalid/x.jpg", 1, "image")
    assert "media_asset" in used
