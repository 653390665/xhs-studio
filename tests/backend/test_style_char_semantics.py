"""写法字数语义：prompt_chars 与 corpus_chars 必须分开。

活库实测（2026-11-18）：library 型 id=3 的 ``char_count`` 是 4782，
而它的 ``skill_md`` 只有 976 字 —— 界面把 4782 显示成「字」，点开只有 976。
同库 evidence 型三列数值相同，所以问题只在蒸馏型上显现。

以前 ``char_count`` 被四种写入点赋予两种含义：

* library / distill  → 语料拼接长度（``stats["chars"]``）
* evidence / builtin / 手动编辑 → 正文长度（``len(markdown)`` / ``len(body)``）

现在 ``serialize_profile`` 额外返回语义固定的两个字段，界面只读
``prompt_chars``。老字段 ``char_count`` 保留，避免破坏其它调用方。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import StyleProfile, User
from backend.app.services.style_distill_service import serialize_profile


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'chars.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db):
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _profile(db, user, *, source, char_count, skill_md, stats_chars=None):
    meta = {}
    if stats_chars is not None:
        meta["stats"] = {"chars": stats_chars}
    row = StyleProfile(
        user_id=user.id,
        name="p",
        status="ready",
        source=source,
        engine="heuristic" if source == "library" else "evidence",
        works_count=12,
        char_count=char_count,
        skill_md=skill_md,
        profile_json=meta,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_library_profile_separates_corpus_from_prompt_length(db):
    """id=3 那种情形：char_count 是语料量，prompt_chars 才是正文。"""
    user = _user(db)
    row = _profile(
        db,
        user,
        source="library",
        char_count=4782,
        skill_md="正" * 976,
        stats_chars=4782,
    )

    payload = serialize_profile(row)

    assert payload["prompt_chars"] == 976, "界面应显示正文长度，不是语料长度"
    assert payload["corpus_chars"] == 4782
    assert payload["char_count"] == 4782, "老字段保留，避免破坏其它调用方"


def test_evidence_profile_prompt_equals_body(db):
    user = _user(db)
    body = "规则" * 800
    row = _profile(
        db, user, source="evidence_distill", char_count=len(body), skill_md=body
    )

    payload = serialize_profile(row)

    assert payload["prompt_chars"] == len(body)
    assert payload["corpus_chars"] == 0, "证据型没有语料字段"


def test_builtin_profile_has_no_corpus_size(db):
    user = _user(db)
    row = _profile(db, user, source="builtin", char_count=9087, skill_md="x" * 9087)

    payload = serialize_profile(row)

    assert payload["prompt_chars"] == 9087
    assert payload["corpus_chars"] == 0


def test_prompt_chars_survives_missing_skill_md(db):
    """没有正文时给 0，而不是让整个列表 500。"""
    user = _user(db)
    row = _profile(db, user, source="library", char_count=1000, skill_md="", stats_chars=1000)

    payload = serialize_profile(row)

    assert payload["prompt_chars"] == 0
    assert payload["corpus_chars"] == 1000
