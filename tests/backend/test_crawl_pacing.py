"""Crawl pacing must not look like a metronome, and must default to safe.

Two defects were found on 2026-10-28 while collecting the AI corpus:

1. ``DataCrawlRequest.time_sleep`` defaulted to ``0``. The most common collection
   path therefore fired platform requests back to back unless every caller
   remembered to pass a delay — the default configuration was the most bot-like
   one available.

2. ``crawl_note_urls`` looped over URLs calling the detail endpoint with no pause
   at all. ``/crawl/data`` at least honoured ``time_sleep``; this one ignored it.

A fixed interval is not a fix either: requests landing at exactly 1500ms, 1500ms,
1500ms are a clearer signature than slightly uneven ones. The pause is now drawn
from a band.
"""

from __future__ import annotations

import statistics

import pytest

from backend.app.services.crawl_guard import (
    DEFAULT_SLEEP_RANGE,
    JITTER_HIGH,
    JITTER_LOW,
    pick_delay,
)


# --- the delay itself -------------------------------------------------------


def test_default_delay_is_inside_the_safe_band():
    for _ in range(50):
        delay = pick_delay()
        assert DEFAULT_SLEEP_RANGE[0] <= delay <= DEFAULT_SLEEP_RANGE[1]


def test_zero_base_still_pauses():
    """``time_sleep=0`` used to mean "no pause". It must not any more."""
    for _ in range(50):
        assert pick_delay(0) > 0


def test_explicit_base_is_jittered_not_fixed():
    samples = [pick_delay(1.5) for _ in range(40)]

    lo = 1.5 * JITTER_LOW
    hi = 1.5 * JITTER_HIGH
    assert all(lo - 0.01 <= s <= hi + 0.01 for s in samples)
    assert len(set(samples)) > 10, "固定间隔本身就是机器人特征"
    assert statistics.pstdev(samples) > 0.05


def test_explicit_range_is_respected():
    for _ in range(30):
        delay = pick_delay(low=3, high=5)
        assert 3 <= delay <= 5


def test_inverted_range_does_not_produce_negative_sleep():
    for _ in range(10):
        assert pick_delay(low=5, high=1) >= 0


def test_negative_base_is_treated_as_absent():
    assert pick_delay(-3) > 0


# --- the request model ------------------------------------------------------


def test_crawl_request_defaults_to_a_pause():
    """The default must be the safe value, not 0."""
    from backend.app.api.platforms.xhs.crawl import DataCrawlRequest

    field = DataCrawlRequest.model_fields["time_sleep"]
    assert field.default > 0, (
        "采集默认不能不限速；旧默认值 0 让最常见的路径成为最像机器人的路径"
    )


def test_crawl_request_still_accepts_explicit_zero():
    """A caller may ask for no pause, but the sleep helper keeps a floor."""
    from backend.app.api.platforms.xhs.crawl import DataCrawlRequest

    req = DataCrawlRequest(account_id=1, mode="search", keyword="x", time_sleep=0)
    assert req.time_sleep == 0
    assert pick_delay(req.time_sleep) > 0
