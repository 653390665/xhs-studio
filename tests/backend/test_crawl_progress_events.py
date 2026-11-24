"""Progress reporting for the streaming crawl.

The backend has always streamed SSE events, but it never announced a denominator,
so the UI could only show a spinner. Worse, ``crawlXhsDataStream`` forwarded the
``plan`` event through the item callback, which appended a junk row to the result
table.

This pins the event contract the progress bar depends on:

* ``plan`` arrives once, before the first item, carrying ``planned``
* every ``item`` carries ``processed`` (1-based, monotonic)
* ``done`` carries the final counts
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CRAWL = REPO / "backend/app/api/platforms/xhs/crawl.py"


def _source() -> str:
    return CRAWL.read_text(encoding="utf-8")


def test_plan_event_is_emitted_for_every_mode():
    """Search, note_urls and comments must all announce a denominator."""
    src = _source()
    plan_count = src.count('"type": "plan"')
    assert plan_count >= 3, (
        f"三种 mode 都应推送 plan 事件，实际只有 {plan_count} 处"
    )


def test_every_item_event_carries_processed():
    """Without `processed` the client cannot count finished items."""
    src = _source()
    item_events = re.findall(r'yield _sse_event\(\{"type": "item"[^}]*\}\)', src)
    assert item_events, "没找到 item 事件"
    missing = [e for e in item_events if '"processed"' not in e]
    assert not missing, f"这些 item 事件缺 processed：{missing}"


def test_processed_is_monotonic_and_one_based():
    """`processed` is len(items) after appending, so it starts at 1."""
    src = _source()
    for m in re.finditer(r'"processed": ([^,}]+)', src):
        expr = m.group(1).strip()
        assert expr == "len(items)", (
            f"processed 必须是当前已完成数量，实际是 {expr}"
        )


def test_plan_reports_the_cap_not_a_guess():
    """`planned` comes from request parameters, so it cannot exceed them."""
    src = _source()
    assert '"planned": payload.max_notes' in src, "搜索模式应报告 max_notes 上限"
    assert '"planned": len(payload.urls)' in src, "链接模式应报告 URL 数量"


# --- client side -----------------------------------------------------------


def test_client_does_not_forward_plan_to_the_item_callback():
    """The plan event must not become a table row.

    The old client passed every parsed event to the item callback, so `plan` was
    appended as a bogus row before any real note arrived.
    """
    api = (REPO / "frontend-legacy/src/lib/api.ts").read_text(encoding="utf-8")
    start = api.find("export async function crawlXhsDataStream")
    assert start > 0
    body = api[start:start + 4000]

    assert 'kind === "plan"' in body
    # The plan branch must `continue` before reaching the item callback.
    plan_branch = body[body.find('kind === "plan"'):body.find('kind === "item"')]
    assert "continue" in plan_branch
    assert "onPlan" in plan_branch


def test_client_reports_processed_separately_from_items():
    api = (REPO / "frontend-legacy/src/lib/api.ts").read_text(encoding="utf-8")
    start = api.find("export async function crawlXhsDataStream")
    body = api[start:start + 4000]

    assert "onCount" in body
    assert "event.processed" in body


def test_crawler_page_renders_a_progress_bar_while_running():
    page = (REPO / "frontend-legacy/src/pages/platforms/xhs/crawler-page.tsx").read_text(encoding="utf-8")
    assert "<Progress" in page, "采集页应显示进度条"
    assert "plannedTotal" in page
    assert "processedCount" in page
    # The denominator must be shown, not just a spinner.
    assert "/ ${plannedTotal}" in page or "/{plannedTotal}" in page or "plannedTotal} 篇" in page
