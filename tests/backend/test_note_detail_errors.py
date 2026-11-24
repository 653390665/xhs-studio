"""Note-detail errors must distinguish throttle from a dead note.

Batch backfill needs this split: a throttled note should be retried later, a dead
note should be skipped and marked unavailable. Both used to be an opaque 502.
"""

from __future__ import annotations

from backend.app.api.platforms.xhs.pc import (
    _detail_error_kind,
    _detail_error_status,
)


def test_rate_limit_codes_are_retryable():
    """300031 is what XHS returns while soft-blocking a session."""
    payload = {"code": 300031, "msg": "当前笔记暂时无法浏览", "data": {}}

    assert _detail_error_kind(payload) == "rate_limited"
    assert _detail_error_status(payload) == 429


def test_missing_note_is_not_retryable():
    payload = {"code": 300011, "msg": "笔记已删除", "data": {}}

    assert _detail_error_kind(payload) == "gone"
    assert _detail_error_status(payload) == 404


def test_empty_payload_stays_generic():
    payload = {"code": 0, "success": True, "data": {}}

    assert _detail_error_kind(payload) == "empty"
    assert _detail_error_status(payload) == 502


def test_payload_with_items_is_not_an_error():
    """A payload carrying a real note must never be classified as an error."""
    from backend.app.api.platforms.xhs.pc import _detail_business_error

    payload = {
        "code": 0,
        "data": {"items": [{"note_card": {"desc": "正文内容"}}]},
    }

    assert _detail_business_error(payload) == ""
