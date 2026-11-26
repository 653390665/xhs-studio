"""采集深度的回归测试：一次 20 条，翻页再采 20 条。

为什么守这几条
--------------
150 条那一轮技术上跑完了，但把账号连续暴露 15 分钟。用户的真实用法是
「搜一页、挑几篇、翻下一页」，所以深度改成 20 条/批，
并且要保证没有任何旁路能一次塞进来超过 20 条。
"""

from __future__ import annotations

import pytest


def test_single_run_cap_is_20():
    from backend.app.services.crawl_guard import MAX_ITEMS_PER_RUN

    assert MAX_ITEMS_PER_RUN == 20, (
        "单批采集上限必须是 20；改这个数字要同时改文档和前端提示"
    )


def test_batch_save_cap_matches_collect_cap():
    """保存上限不能高于采集上限，否则「采 20 存 100」会绕过深度限制。"""
    from backend.app.services.crawl_guard import MAX_ITEMS_PER_RUN, MAX_NOTES_PER_BATCH

    assert MAX_NOTES_PER_BATCH <= MAX_ITEMS_PER_RUN, (
        "保存批次上限高于采集上限，深度限制就形同虚设"
    )


def test_batch_save_rejects_more_than_cap():
    from pydantic import ValidationError

    from backend.app.api.notes import BatchSaveNotesRequest
    from backend.app.services.crawl_guard import MAX_NOTES_PER_BATCH

    def item(i: int) -> dict:
        return {
            "note_id": f"n{i}",
            "note_url": f"https://www.xiaohongshu.com/explore/n{i}",
            "title": f"标题{i}",
            "content": "正文" * 40,
        }

    # 正好 20 条可以
    ok = BatchSaveNotesRequest(account_id=1, notes=[item(i) for i in range(20)])
    assert len(ok.notes) == 20

    # 21 条必须被拒
    with pytest.raises(ValidationError):
        BatchSaveNotesRequest(
            account_id=1, notes=[item(i) for i in range(MAX_NOTES_PER_BATCH + 1)]
        )


def test_max_wait_is_shorter_than_frontend_timeout_window():
    """后端排队等待不能远超前端超时，否则用户看到失败、后端还在白等。"""
    import inspect

    from backend.app.services.crawl_guard import CrawlGuard

    sig = inspect.signature(CrawlGuard.acquire)
    default_wait = sig.parameters["max_wait"].default
    assert default_wait <= 45, (
        f"max_wait={default_wait}s 太长：前端 detail 25 秒就 abort，"
        "后端等更久只会产生「用户已看到失败、请求才发出去」的浪费"
    )


def test_low_follower_profile_fanout_is_small():
    """低粉爆款逐个查主页，profile_page 只有 2 次/分钟，默认值不能太大。"""
    import inspect

    from backend.app.services.note_metrics_service import enrich_items_with_authors

    sig = inspect.signature(enrich_items_with_authors)
    default_profiles = sig.parameters["max_profiles"].default
    assert default_profiles <= 3, (
        f"max_profiles={default_profiles}：profile_page 2 次/分钟，"
        "查超过 3 个会中途抛 CrawlThrottled"
    )


def test_enrich_does_not_double_sleep():
    """adapter 自己会 pace，enrich 再 sleep 是重复计时，会误导限额。"""
    import inspect

    from backend.app.services.note_metrics_service import enrich_items_with_authors

    sig = inspect.signature(enrich_items_with_authors)
    assert sig.parameters["sleep_seconds"].default == 0, (
        "enrich_items_with_authors 不该自带 sleep：adapter 的 acquire 已经有抖动"
    )
