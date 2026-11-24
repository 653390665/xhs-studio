"""Data truth helpers used by publish feedback and account prompts."""

from __future__ import annotations

from backend.app.services.account_service import profile_fans


def test_profile_fans_accepts_all_historical_keys():
    assert profile_fans({"fans": 120}) == 120
    assert profile_fans({"followers": "1.2万"}) == 12000
    assert profile_fans({"fans_count": "3,400"}) == 3400
    assert profile_fans({"follower_count": 88}) == 88
    assert profile_fans('{"followers": 66}') == 66


def test_profile_fans_handles_empty_and_invalid_values():
    assert profile_fans(None) == 0
    assert profile_fans({}) == 0
    assert profile_fans("not json") == 0
    assert profile_fans({"fans": "abc"}) == 0
