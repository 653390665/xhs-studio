"""发布时间：``created_at`` 是采集时间，不是发布时间。

这两个事实以前混在一起，导致「近 7 天的低粉爆款」这类筛选根本做不了：
一条今天采到的笔记可能是三年前发的。

解析规则：秒 / 毫秒 / 文本三种形态；解析不出来返回 ``None``（未知），
**不能**默认成「现在」——那会让日期读不出来的笔记通过所有近期筛选。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from backend.app.services.note_metrics_service import (
    extract_note_metrics,
    parse_published_at,
)


def test_parses_unix_seconds():
    """Unix seconds → naive Asia/Shanghai wall clock (the schema convention)."""
    assert parse_published_at(1730184000) == datetime(2024, 10, 29, 14, 40)


def test_parses_unix_milliseconds():
    assert parse_published_at(1730184000000) == datetime(2024, 10, 29, 14, 40)


def test_parses_text_dates():
    assert parse_published_at("2026-11-04 20:08") == datetime(2026, 11, 4, 20, 8)
    assert parse_published_at("2026-11-04 20:08:31") == datetime(2026, 11, 4, 20, 8, 31)
    assert parse_published_at("2026-11-04") == datetime(2026, 11, 4)
    assert parse_published_at("2026/11/04") == datetime(2026, 11, 4)


def test_unknown_values_return_none_not_now():
    for value in (None, "", "   ", 0, -1, "昨天", "N/A", True, [], {}):
        assert parse_published_at(value) is None, value


def test_normalizes_to_naive_shanghai_time():
    """Storage convention: naive Asia/Shanghai, matching the rest of the schema."""
    parsed = parse_published_at(1730184000)
    assert parsed is not None
    assert parsed.tzinfo is None


def test_extract_note_metrics_reads_the_web_card_time():
    raw = {
        "note_card": {
            "note_id": "abc",
            "time": 1730184000,
            "interact_info": {"liked_count": "1,234"},
        }
    }
    metrics = extract_note_metrics(raw)
    assert metrics["published_at"] == datetime(2024, 10, 29, 14, 40)
    assert metrics["likes"] == 1234


def test_extract_note_metrics_reads_redfox_publish_time():
    raw = {"workId": "w1", "workPublishTime": "2026-11-04 20:08"}
    metrics = extract_note_metrics(raw)
    assert metrics["published_at"] == datetime(2026, 11, 4, 20, 8)


def test_extract_note_metrics_reads_douyin_extract_published_at():
    """抖音转写稿把时间放在顶层 ``published_at``，以前只认 published/time。"""
    raw = {"published_at": "2026-06-09", "title": "一条转写稿"}
    metrics = extract_note_metrics(raw)
    assert metrics["published_at"] == datetime(2026, 6, 9)


def test_missing_time_stays_none():
    metrics = extract_note_metrics({"note_card": {"note_id": "abc"}})
    assert metrics["published_at"] is None


def test_extract_note_metrics_reads_top_level_items():
    """详情接口把 ``items`` 放在顶层，搜索接口才包在 ``data`` 里。

    只认 ``data.items`` 时，详情采集的 109 条笔记发布时间全是 NULL。
    """
    raw = {
        "code": 0,
        "items": [
            {
                "id": "x1",
                "note_card": {
                    "note_id": "x1",
                    "time": 1790953186000,
                    "title": "顶层 items 的一篇",
                },
            }
        ],
    }
    metrics = extract_note_metrics(raw)
    assert metrics["published_at"] == datetime(2026, 10, 2, 22, 59, 46)
