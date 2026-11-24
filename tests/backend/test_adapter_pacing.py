"""Adapter-layer pacing: the account got flagged because the budget was optional.

On 2026-10-28 a body crawl pulled 294 note details at ~29 requests/minute against
a documented limit of 5. The guard existed and worked — it just lived in the API
handler, so a script calling the adapter directly never touched it.

These tests pin the fix: the budget is enforced at the adapter, which every
caller goes through, and refusing does not silently look like success.
"""
from __future__ import annotations

import time

import pytest

from backend.app.adapters.xhs import pc_api_adapter
from backend.app.services import crawl_guard as cg
from backend.app.services.crawl_guard import ACTION_LIMITS, CrawlGuard, CrawlThrottled


@pytest.fixture()
def guard(monkeypatch):
    """A fresh guard wired into the module the adapter imports at call time."""
    instance = CrawlGuard()
    monkeypatch.setattr(cg, "get_crawl_guard", lambda: instance)
    return instance


# --- the ceiling itself -----------------------------------------------------


def test_note_detail_limit_is_evidence_backed():
    """The limit must sit between the proven-safe and proven-unsafe rates.

    Measured history (see crawl_guard docstring):

        9.6 /min  → 140 notes, 100% body coverage, completed
        28  /min  → session invalidated mid-run

    A number below the proven-safe rate is not caution, it is an unmeasured
    assumption — the earlier 3/min turned an 8-minute job into 7.5 hours.
    """
    assert 9 <= ACTION_LIMITS["note_detail"] < 28, (
        "note_detail 必须落在实测可用(9.6)与实测失败(28)之间，"
        "改这个数字前先补一个新的实测数据点"
    )


def test_all_actions_have_a_limit():
    for action in ("profile_page", "note_detail", "search"):
        assert action in ACTION_LIMITS
        assert 0 < ACTION_LIMITS[action] < 28, "任何动作都不该超过已证失败的 28/分钟"


def test_session_pause_is_shorter_than_freshness_cooldown():
    """Continuing an unfinished job must not pay the re-crawl cooldown."""
    from backend.app.services.crawl_guard import (
        ACCOUNT_COOLDOWN_SECONDS,
        SESSION_PAUSE_MINUTES,
    )

    assert SESSION_PAUSE_MINUTES * 60 < ACCOUNT_COOLDOWN_SECONDS, (
        "补正文是继续未完成的任务，不该等『重复抓同样内容』的冷却"
    )


# --- acquire() --------------------------------------------------------------


def test_acquire_blocks_until_budget_frees(monkeypatch):
    """Must wait for a slot, not slip through — verified without really waiting.

    ``crawl_guard`` binds ``time`` at import, so ``time.sleep`` must be replaced
    on the module object. A virtual clock advances instead of sleeping.
    """
    guard = CrawlGuard()
    limit = ACTION_LIMITS["note_detail"]
    slept: list[float] = []
    clock = {"now": 1000.0}

    def fake_monotonic():
        return clock["now"]

    def fake_sleep(seconds):
        slept.append(seconds)
        clock["now"] += max(seconds, 0.001)

    class FakeTime:
        monotonic = staticmethod(fake_monotonic)
        sleep = staticmethod(fake_sleep)

    monkeypatch.setattr(cg, "time", FakeTime)

    for _ in range(limit):
        guard.acquire("cookie:test", "note_detail", max_wait=90, jitter=False)
    guard.acquire("cookie:test", "note_detail", max_wait=90, jitter=False)

    assert slept, f"超出 {limit} 次/分钟后应当等待，而不是直接放行"


def test_acquire_refuses_instead_of_exceeding():
    guard = CrawlGuard()
    key = "cookie:test"
    for _ in range(ACTION_LIMITS["note_detail"]):
        guard.consume_quietly(key, "note_detail")
    with pytest.raises(CrawlThrottled) as exc:
        guard.acquire(key, "note_detail", max_wait=0)
    assert "限额" in str(exc.value)


def test_acquire_spaces_requests_with_jitter(monkeypatch):
    """Even inside budget, calls are spaced — a metronome is a bot signature."""
    guard = CrawlGuard()
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    guard.acquire("cookie:x", "search", jitter=True)
    assert slept, "jitter 打开时应当 sleep"
    assert 0 < slept[0] < 10


def test_acquire_without_jitter_sleeps_nothing_but_consumes():
    guard = CrawlGuard()
    key = "cookie:y"
    for _ in range(ACTION_LIMITS["search"]):
        guard.acquire(key, "search", jitter=False)
    # Budget exhausted, and nothing blocked because the window never overflowed.
    assert guard.would_allow(key, "search") is False


# --- failure is explicit ----------------------------------------------------


def test_crawl_throttled_is_a_runtime_error():
    assert issubclass(CrawlThrottled, RuntimeError)


# --- bucket key -------------------------------------------------------------


def test_bucket_key_is_stable_per_cookie_set():
    a = pc_api_adapter.XhsPcApiAdapter("web_session=abc; a1=xyz")
    b = pc_api_adapter.XhsPcApiAdapter("web_session=abc; a1=xyz")
    c = pc_api_adapter.XhsPcApiAdapter("web_session=other")
    assert a._budget_key == b._budget_key
    assert a._budget_key != c._budget_key
    assert a._budget_key.startswith("cookie:")


def test_bucket_key_does_not_leak_the_cookie():
    raw = "web_session=supersecretvalue"
    assert "supersecretvalue" not in pc_api_adapter.XhsPcApiAdapter(raw)._budget_key


# --- every platform call is paced ------------------------------------------


def test_every_platform_call_consults_the_guard(guard, monkeypatch):
    """No adapter method may reach the platform without pacing first."""
    adapter = pc_api_adapter.XhsPcApiAdapter("web_session=abc")
    actions: list[str] = []

    def fake_acquire(key, action, **kwargs):
        actions.append(action)

    monkeypatch.setattr(guard, "acquire", fake_acquire)

    # Force the API layer to fail fast so we only observe the pacing call.
    def boom(*a, **k):
        raise RuntimeError("fake api failure")

    monkeypatch.setattr(adapter, "_api", boom)

    calls = {
        "search": lambda: adapter.search_note("kw"),
        "note_detail": lambda: adapter.get_note_info("https://example.invalid/1"),
        "profile_page": lambda: adapter.get_user_notes(
            "https://www.xiaohongshu.com/user/profile/" + "a" * 24
        ),
    }
    for expected, call in calls.items():
        with pytest.raises(Exception):
            call()
        assert expected in actions, f"{expected} 未经限速"


def test_get_note_comments_paces_even_though_it_swallows_errors(guard, monkeypatch):
    """Comments returns a tuple on failure; it must still have paced."""
    adapter = pc_api_adapter.XhsPcApiAdapter("web_session=abc")
    actions: list[str] = []
    monkeypatch.setattr(guard, "acquire", lambda k, a, **kw: actions.append(a))
    monkeypatch.setattr(adapter, "_api", lambda: (_ for _ in ()).throw(RuntimeError("x")))

    ok, msg, payload = adapter.get_note_comments("https://example.invalid/1")
    assert ok is False and payload is None
    assert "note_detail" in actions


# --- non-consuming check ----------------------------------------------------


def test_would_allow_does_not_consume_budget():
    guard = CrawlGuard()
    key = 1
    for _ in range(ACTION_LIMITS["profile_page"]):
        assert guard.would_allow(key, "profile_page") is True
    assert guard.would_allow(key, "profile_page") is True, "查询不应消耗配额"

    for _ in range(ACTION_LIMITS["profile_page"]):
        assert guard.allow(key, "profile_page") is True
    assert guard.would_allow(key, "profile_page") is False
