"""P2-16：提炼 → 应用 → 再提炼，已应用那份必须被原地更新。

实测：`_find_same_input` 以前要求 ``row.account_id == account_id`` 完全相等。
提炼页调 from-library 时不传账号（None），应用后该行是 1，于是再提炼时
``None != 1`` 匹配不上——新建一份副本，而账号继续用旧的。
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import StyleProfile, User
from backend.app.services.style_distill_service import _find_same_input


def _fingerprint(note_ids):
    normalized = ",".join(str(int(v)) for v in sorted(set(note_ids)))
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 's.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _profile(db, user, *, pid, account_id, fingerprint, status="ready"):
    from datetime import datetime

    row = StyleProfile(
        id=pid,
        user_id=user.id,
        name=f"p{pid}",
        status=status,
        source="library",
        engine="heuristic",
        account_id=account_id,
        works_count=12,
        char_count=900,
        skill_md="# x",
        profile_json={"input_fingerprint": fingerprint, "note_ids": [1, 2, 3]},
        created_at=datetime(2026, 11, 14, 4, 16, 11),
        updated_at=datetime(2026, 11, 14, 4, 16, 11),
    )
    db.add(row)
    db.commit()
    return row


def test_same_fingerprint_matches_even_after_it_was_applied(db):
    """提炼页不传账号，应用后该行有了账号——再提炼仍要命中它。"""
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    fp = _fingerprint([1, 2, 3])
    applied = _profile(db, user, pid=7, account_id=1, fingerprint=fp, status="applied")

    found = _find_same_input(db, user, fingerprint=fp, account_id=None)

    assert found is not None, "同一批素材再提炼时没匹配到已应用那份 → 会新建副本"
    assert found.id == applied.id
    assert len(db.scalars(select(StyleProfile)).all()) == 1


def test_matching_keeps_the_account_binding(db):
    """原地更新不能把写法从账号上解绑。"""
    user = User(username="u2", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    fp = _fingerprint([4, 5])
    row = _profile(db, user, pid=8, account_id=1, fingerprint=fp, status="applied")

    found = _find_same_input(db, user, fingerprint=fp, account_id=None)
    assert found is not None and found.id == row.id

    # 模拟原地更新的写回：只改正文/统计，不动 account_id
    found.skill_md = "# 更新后的正文"
    found.char_count = 1200
    db.commit()
    db.refresh(row)

    assert row.account_id == 1, "重蒸之后写法被解绑了"
    assert row.status == "applied"
    assert row.skill_md == "# 更新后的正文"


def test_exact_account_still_wins_when_both_exist(db):
    """同指纹有两行时，账号完全匹配的那行优先。"""
    user = User(username="u3", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    fp = _fingerprint([9, 10])
    _profile(db, user, pid=1, account_id=None, fingerprint=fp)
    exact = _profile(db, user, pid=2, account_id=1, fingerprint=fp)

    found = _find_same_input(db, user, fingerprint=fp, account_id=1)
    assert found is not None and found.id == exact.id
