"""按作者采集的 URL 归一化测试。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.api.platforms.xhs.pc import _profile_url

UID = "59850e2850c4b47ddd4668d3"


def test_bare_id_becomes_profile_url():
    assert _profile_url(UID) == f"https://www.xiaohongshu.com/user/profile/{UID}"


def test_profile_url_is_passed_through():
    url = f"https://www.xiaohongshu.com/user/profile/{UID}"
    assert _profile_url(url) == url


def test_url_with_token_is_not_double_tokenised():
    url = f"https://www.xiaohongshu.com/user/profile/{UID}?xsec_token=ABC&xsec_source=pc_search"
    assert _profile_url(url) == url


def test_separate_token_parameter_is_appended():
    out = _profile_url(UID, "ABC123")
    assert out.startswith(f"https://www.xiaohongshu.com/user/profile/{UID}")
    assert "xsec_token=ABC123" in out
    assert "xsec_source=pc_search" in out


def test_path_shaped_input_is_accepted():
    out = _profile_url(f"user/profile/{UID}")
    assert out == f"https://www.xiaohongshu.com/user/profile/{UID}"


def test_truncated_id_is_rejected_with_the_real_reason():
    """The failure that wasted a whole debug cycle.

    A 22-char id made the platform answer ``{success: true, data: null}``, which
    reads as "account has no notes" or "rate limited". It was neither — the id
    was truncated when copied out of a terminal.
    """
    truncated = UID[:-2]
    with pytest.raises(HTTPException) as exc:
        _profile_url(truncated)
    assert exc.value.status_code == 400
    detail = str(exc.value.detail)
    assert "24 位" in detail or "格式" in detail
    assert truncated in detail


def test_non_hex_id_is_rejected():
    with pytest.raises(HTTPException):
        _profile_url("not-an-author-id")


def test_empty_input_is_rejected():
    with pytest.raises(HTTPException):
        _profile_url("   ")
