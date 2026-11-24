"""同一指纹下必须更新「生效中的那一份」，而不是库里碰巧排第一的旧行。

活库实测：7/8/11 与 10/12/13 是两组同语料反复蒸出来的产物，指纹完全相同。
旧实现按查询顺序返回第一条，于是「重蒸同一批」可能更新历史行，而
``applied`` 的那份仍在给写稿注入旧规则——用户看到新报告，账号却照旧写。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import StyleProfile, User
from backend.app.services import evidence_distill_service, style_distill_service

FP = "9ac6985e4708ac58"


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'styles.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db):
    user = User(username="u1", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _profile(db, user, *, pid, status, updated, fp=FP, engine="evidence", source="evidence_distill"):
    row = StyleProfile(
        id=pid,
        user_id=user.id,
        name=f"p{pid}",
        status=status,
        source=source,
        engine=engine,
        works_count=147,
        char_count=100,
        skill_md="# x",
        profile_json={"input_fingerprint": fp, "corpus_label": "同一个语料"},
        created_at=updated,
        updated_at=updated,
    )
    db.add(row)
    db.commit()
    return row


def test_evidence_pick_prefers_applied_over_smaller_id(db):
    user = _user(db)
    base = datetime(2026, 11, 14, 4, 16, 11)
    _profile(db, user, pid=7, status="ready", updated=base)
    _profile(db, user, pid=8, status="ready", updated=base)
    chosen = _profile(db, user, pid=11, status="applied", updated=base)

    found = evidence_distill_service._find_same_evidence_input(
        db, user, fingerprint=FP, account_id=None, source="evidence_distill"
    )
    assert found is not None
    assert found.id == chosen.id


def test_evidence_pick_prefers_newest_when_none_applied(db):
    user = _user(db)
    base = datetime(2026, 11, 14, 4, 16, 11)
    _profile(db, user, pid=10, status="ready", updated=base)
    newer = _profile(db, user, pid=12, status="ready", updated=base + timedelta(hours=3))

    found = evidence_distill_service._find_same_evidence_input(
        db, user, fingerprint=FP, account_id=None, source="evidence_distill"
    )
    assert found is not None
    assert found.id == newer.id


def test_library_pick_uses_the_same_ranking(db):
    user = _user(db)
    base = datetime(2026, 11, 14, 4, 16, 11)
    _profile(
        db, user, pid=3, status="ready", updated=base,
        engine="heuristic", source="library",
    )
    applied = _profile(
        db, user, pid=4, status="applied", updated=base,
        engine="heuristic", source="library",
    )

    found = style_distill_service._find_same_input(
        db, user, fingerprint=FP, account_id=None
    )
    assert found is not None
    assert found.id == applied.id


def test_no_match_returns_none(db):
    user = _user(db)
    _profile(db, user, pid=2, status="ready", updated=datetime(2026, 11, 14, 4, 16, 11))
    assert (
        evidence_distill_service._find_same_evidence_input(
            db, user, fingerprint="deadbeefdeadbeef", account_id=None,
            source="evidence_distill",
        )
        is None
    )
