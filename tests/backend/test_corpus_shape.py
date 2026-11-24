"""shape 数的是「已拿到正文的笔记」，不是「已经能蒸馏的笔记」。

真实现象：从素材库加了 4 篇、标了体裁，但在点「分配基线/反例」之前，
接口返回 `authors: 0, notes: 0`，界面写着「这集是单作者（0 篇），可以蒸写法」。
把「还没分角色」误报成「这集是空的」正是这个项目反复出现的缺陷。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import CorpusSet, Note, PlatformAccount, User
from backend.app.services.corpus_service import add_notes_to_set, corpus_shape

BODY = (
    "让你把表格拖上去，结果你拖了半天也没拖上去。你不是说自己精通办公软件吗？"
    "你先点击表格，然后选择布局。点赞收藏，学会了吗。#Excel #办公技巧"
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shape.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="shape-user", password_hash="x")
    session.add(user)
    session.flush()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="号", status="active"
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    try:
        yield session, user, account
    finally:
        session.close()


def _corpus(db, user):
    corpus = CorpusSet(user_id=user.id, name="shape", kind="account", status="draft")
    db.add(corpus)
    db.commit()
    return corpus


def _note(db, user, account, index, author="同一作者"):
    note = Note(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id=f"s{index}",
        title=f"标题{index}",
        content=BODY,
        author_name=author,
        author_id=f"a{index}",
        author_fans=1000,
        author_fans_status="known",
        like_count=1500,
        source_type="discovery",
    )
    db.add(note)
    db.commit()
    return note


def test_shape_counts_bodies_before_roles_are_assigned(db):
    session, user, account = db
    corpus = _corpus(session, user)
    notes = [_note(session, user, account, i) for i in range(3)]
    add_notes_to_set(session, user, corpus, [n.id for n in notes])

    shape = corpus_shape(session, corpus)

    assert shape["notes"] == 3
    assert shape["authors"] == 1
    assert shape["single_author"] is True
    # No genre and no roles yet → not distillable, but the shape is still known.
    assert shape["fans_measured"] == 3
    assert shape["breakouts"] == 3


def test_shape_ignores_members_without_bodies(db):
    session, user, account = db
    corpus = _corpus(session, user)
    note = _note(session, user, account, 0)
    short = Note(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id="short",
        title="短",
        content="太短",
        author_name="同一作者",
        source_type="discovery",
    )
    session.add(short)
    session.commit()
    add_notes_to_set(session, user, corpus, [note.id, short.id])

    shape = corpus_shape(session, corpus)

    assert shape["notes"] == 1
