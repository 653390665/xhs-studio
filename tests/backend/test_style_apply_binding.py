"""P2-17：把别的账号正在用的写法应用过来，会静默解绑。

实测：`apply_to_account` 只降级**目标账号**的其它 applied 行，对
``profile.account_id`` 原本指向谁不做任何检查；而 ``unapply_from_account``
对同一状态是报错的。同一个状态两种待遇。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import PlatformAccount, StyleProfile, User
from backend.app.services.style_distill_service import (
    StyleDistillError,
    apply_to_account,
    unapply_from_account,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bind.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _setup(db):
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    a = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="A", status="active"
    )
    b = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="B", status="active"
    )
    db.add_all([a, b])
    db.commit()
    db.refresh(a)
    db.refresh(b)
    profile = StyleProfile(
        user_id=user.id,
        name="共享写法",
        status="ready",
        source="library",
        engine="heuristic",
        works_count=12,
        char_count=900,
        skill_md="# x",
        profile_json={},
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return user, a, b, profile


def test_apply_to_second_account_is_refused_not_silent(db):
    """写法已在 A 上生效时，直接在 B 上应用必须报错，不能静默解绑 A。"""
    user, a, b, profile = _setup(db)
    apply_to_account(db, user, profile, account_id=a.id)
    db.refresh(profile)
    assert profile.account_id == a.id and profile.status == "applied"

    with pytest.raises(StyleDistillError) as exc:
        apply_to_account(db, user, profile, account_id=b.id)
    assert "当前应用在账号" in str(exc.value)

    db.refresh(profile)
    assert profile.account_id == a.id, "报错之后不该已经改绑"
    assert profile.status == "applied", "A 的风格不该被静默摘掉"


def test_apply_and_unapply_treat_the_same_state_the_same_way(db):
    """同一状态（已绑在别的账号）：apply 与 unapply 都该报错。"""
    user, a, b, profile = _setup(db)
    apply_to_account(db, user, profile, account_id=a.id)

    with pytest.raises(StyleDistillError):
        apply_to_account(db, user, profile, account_id=b.id)
    with pytest.raises(StyleDistillError):
        unapply_from_account(db, user, profile, account_id=b.id)


def test_apply_to_same_account_again_is_idempotent(db):
    """在本来就在用的账号上重复应用，不该报错。"""
    user, a, _b, profile = _setup(db)
    apply_to_account(db, user, profile, account_id=a.id)
    again = apply_to_account(db, user, profile, account_id=a.id)

    assert again.account_id == a.id
    assert again.status == "applied"


def test_apply_after_unapply_on_old_account_works(db):
    """先取消应用再改绑，是受支持的路径。"""
    user, a, b, profile = _setup(db)
    apply_to_account(db, user, profile, account_id=a.id)
    unapply_from_account(db, user, profile, account_id=a.id)

    moved = apply_to_account(db, user, profile, account_id=b.id)
    assert moved.account_id == b.id
    assert moved.status == "applied"
