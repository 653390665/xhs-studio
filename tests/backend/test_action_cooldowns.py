"""Cooldowns are per action, not per account.

The failure this pins: after a listing crawl set the 30-minute "don't re-crawl
the same listing" cooldown, the first body backfill returned

    429 该账号刚采集过列表，请 27 分钟后再补正文

for a job that had never run. One timer served two unrelated actions.
"""
from __future__ import annotations

from backend.app.services.crawl_guard import (
    ACCOUNT_COOLDOWN_SECONDS,
    SESSION_PAUSE_MINUTES,
    CrawlGuard,
)


def test_listing_cooldown_does_not_block_body_backfill():
    guard = CrawlGuard()
    account = 1

    # A listing crawl just finished.
    guard.mark_run(account, "profile_page")

    assert guard.cooldown_remaining(account, "profile_page", ACCOUNT_COOLDOWN_SECONDS) > 0
    # The body pass has never run, so it must not inherit that timer.
    assert guard.cooldown_remaining(
        account, "note_detail", SESSION_PAUSE_MINUTES * 60
    ) == 0


def test_body_backfill_cooldown_does_not_block_a_listing_crawl():
    guard = CrawlGuard()
    guard.mark_run(1, "note_detail")
    assert guard.cooldown_remaining(1, "profile_page", ACCOUNT_COOLDOWN_SECONDS) == 0


def test_same_action_is_still_cooldown_gated():
    guard = CrawlGuard()
    guard.mark_run(1, "note_detail")
    assert guard.cooldown_remaining(1, "note_detail", SESSION_PAUSE_MINUTES * 60) > 0


def test_cooldowns_are_per_account():
    guard = CrawlGuard()
    guard.mark_run(1, "note_detail")
    assert guard.cooldown_remaining(1, "note_detail", 300) > 0
    assert guard.cooldown_remaining(2, "note_detail", 300) == 0


def test_legacy_helpers_map_to_the_listing_action():
    """``mark_account_run`` predates per-action timers; keep it meaningful."""
    guard = CrawlGuard()
    guard.mark_account_run(1)
    assert guard.account_cooldown_remaining(1) > 0
    assert guard.cooldown_remaining(1, "note_detail", 300) == 0


def test_reset_clears_action_timers():
    guard = CrawlGuard()
    guard.mark_run(1, "note_detail")
    guard.reset()
    assert guard.cooldown_remaining(1, "note_detail", 300) == 0
