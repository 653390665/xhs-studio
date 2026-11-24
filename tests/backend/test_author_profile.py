"""Author profile parsing: follower stats live in data.interactions."""

from __future__ import annotations

from backend.app.services.note_metrics_service import normalize_author_profile


def test_normalize_author_profile_parses_interactions():
    payload = {
        "data": {
            "basic_info": {"nickname": "Neo阿桑", "red_id": "63630032846"},
            "interactions": [
                {"type": "follows", "name": "关注", "count": "5"},
                {"type": "fans", "name": "粉丝", "count": "3"},
                {"type": "interaction", "name": "获赞与收藏", "count": "15"},
            ],
            "posted": 4,
            "liked": 8,
        }
    }

    profile = normalize_author_profile(payload)

    assert profile["nickname"] == "Neo阿桑"
    assert profile["fans"] == 3
    assert profile["follows"] == 5
    assert profile["notes"] == 4
    assert profile["interactions"] == 15


def test_normalize_author_profile_falls_back_to_basic_info():
    payload = {
        "data": {
            "basic_info": {"nickname": "老用户", "fans": 1200, "follows": 30, "note_num": 9},
        }
    }

    profile = normalize_author_profile(payload)

    assert profile["fans"] == 1200
    assert profile["follows"] == 30
    assert profile["notes"] == 9


def test_normalize_author_profile_handles_w_units():
    payload = {
        "data": {
            "basic_info": {"nickname": "大V"},
            "interactions": [
                {"type": "fans", "name": "粉丝", "count": "4.2w"},
                {"type": "follows", "name": "关注", "count": "88"},
                {"type": "interaction", "name": "获赞与收藏", "count": "10w+"},
            ],
            "posted": 120,
        }
    }

    profile = normalize_author_profile(payload)

    assert profile["fans"] == 42000
    assert profile["follows"] == 88
    assert profile["interactions"] == 100000
    assert profile["notes"] == 120
