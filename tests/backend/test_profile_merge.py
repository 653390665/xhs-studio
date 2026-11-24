"""A login must not erase numbers it did not fetch.

Reported symptom: after re-scanning the QR code, the account card showed
``- / - / -`` where it had shown ``4 / 5 / 16``. ``user/me`` returns the profile
without the interaction counts, and the old code did

    account.profile_json = json.dumps(new_profile)

which replaced the whole document. A login proves the account is reachable; it
proves nothing about how many followers it has.

Rule under test: **a null/empty value never overwrites a known one.**
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import PlatformAccount, User
from backend.app.services.account_service import (
    merge_profile,
    upsert_platform_account_from_login,
)


# --- the merge rule ---------------------------------------------------------


def test_null_does_not_overwrite_a_known_value():
    assert merge_profile({"followers": 4}, {"followers": None}) == {"followers": 4}


def test_empty_string_does_not_overwrite():
    assert merge_profile({"red_id": "abc"}, {"red_id": "   "}) == {"red_id": "abc"}


def test_empty_dict_does_not_overwrite():
    assert merge_profile({"raw": {"a": 1}}, {"raw": {}}) == {"raw": {"a": 1}}


def test_new_value_wins_when_it_has_information():
    assert merge_profile({"followers": 4}, {"followers": 9})["followers"] == 9


def test_nested_dicts_merge_instead_of_replacing():
    old = {"raw": {"nickname": "阿桑", "fans": 12}}
    new = {"raw": {"nickname": "阿桑2", "fans": None}}
    merged = merge_profile(old, new)
    assert merged["raw"]["nickname"] == "阿桑2"
    assert merged["raw"]["fans"] == 12, "嵌套里的空值也不能覆盖"


def test_unknown_keys_are_preserved():
    merged = merge_profile({"desc": "老简介", "followers": 4}, {"nickname": "新名"})
    assert merged["desc"] == "老简介"
    assert merged["followers"] == 4
    assert merged["nickname"] == "新名"


def test_merge_handles_empty_inputs():
    assert merge_profile({}, {"a": 1}) == {"a": 1}
    assert merge_profile({"a": 1}, {}) == {"a": 1}
    assert merge_profile({}, {}) == {}


# --- the real code path -----------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'acct.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="acct-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    try:
        yield session, user
    finally:
        session.close()


def _login(db, user, *, followers):
    return upsert_platform_account_from_login(
        db=db,
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        user_info={
            "external_user_id": "000000000000000000000001",
            "nickname": "阿桑",
            "profile": {"red_id": "63630032846", "followers": followers},
        },
        cookies_text="c=1",
    )


def test_second_login_keeps_the_known_follower_count(db):
    """The exact regression: 4 followers → relogin → still 4, not null."""
    session, user = db
    account, _ = _login(session, user, followers=4)
    session.commit()
    assert json.loads(account.profile_json)["followers"] == 4

    again, action = _login(session, user, followers=None)
    session.commit()
    stored = json.loads(again.profile_json)
    assert action == "updated"
    assert stored["followers"] == 4, "重新登录不该把已知粉丝数清空"


def test_first_login_without_counts_stores_what_it_has(db):
    session, user = db
    account, action = _login(session, user, followers=None)
    session.commit()
    stored = json.loads(account.profile_json)
    assert action == "created"
    assert stored["red_id"] == "63630032846"


def test_a_real_new_count_still_updates(db):
    session, user = db
    _login(session, user, followers=4)
    session.commit()
    account, _ = _login(session, user, followers=11)
    session.commit()
    assert json.loads(account.profile_json)["followers"] == 11
