"""从素材库往语料集加笔记：主题集此前没有填充路径。

`/collect` 只能爬账号主页，所以按关键词建的主题集「建得出来、永远 0 篇」。
这组测试守住三件事：

* 有正文的笔记加入即 ``ok``，短正文进 ``pending_body`` 而不是假装可用；
* 重复加入是幂等的，不产生第二行；
* 加进来的笔记默认 ``unclassified``，只有显式传 genre 才写入。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import CorpusMember, CorpusSet, Note, PlatformAccount, User
from backend.app.services.corpus_service import (
    MAX_NOTES_PER_SET,
    MIN_MEMBER_BODY_CHARS,
    CorpusError,
    add_notes_to_set,
    assign_roles,
    distillable_members,
    remove_member,
)

BODY = (
    "让你把表格拖上去，结果你拖了半天也没拖上去。你不是说自己精通办公软件吗？"
    "你先点击表格，然后选择布局。点赞收藏，学会了吗。#Excel #办公技巧"
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'members.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="members-user", password_hash="x")
    session.add(user)
    session.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        nickname="号",
        status="active",
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    try:
        yield session, user, account
    finally:
        session.close()


def _corpus(db, user, kind="topic"):
    corpus = CorpusSet(user_id=user.id, name="t", kind=kind, status="draft")
    db.add(corpus)
    db.commit()
    return corpus


def _note(db, user, account, index, body=BODY, likes=0):
    note = Note(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id=f"n{index}",
        title=f"标题{index}",
        content=body,
        author_name=f"作者{index}",
        source_type="discovery",
        like_count=likes,
    )
    db.add(note)
    db.commit()
    return note


def test_notes_with_bodies_are_added_as_ok_and_distillable(db):
    session, user, account = db
    corpus = _corpus(session, user)
    # Distinct engagement so the median split can produce baseline/negative.
    notes = [
        _note(session, user, account, i, likes=(i + 1) * 100) for i in range(3)
    ]

    result = add_notes_to_set(session, user, corpus, [n.id for n in notes], genre="opinion")

    assert result["added"] == 3
    assert result["pending_body"] == 0
    members = session.query(CorpusMember).all()
    assert {m.collect_status for m in members} == {"ok"}
    assert {m.genre for m in members} == {"opinion"}
    # Membership is not enough: distillation reads only baseline/negative rows.
    assert distillable_members(session, corpus) == []
    assign_roles(session, user, corpus)
    assert len(distillable_members(session, corpus)) == 2


def test_short_notes_go_to_pending_body_not_ok(db):
    session, user, account = db
    corpus = _corpus(session, user)
    note = _note(session, user, account, 0, body="太短了")

    result = add_notes_to_set(session, user, corpus, [note.id])

    assert result["added"] == 1
    assert result["pending_body"] == 1
    member = session.query(CorpusMember).one()
    assert member.collect_status == "pending_body"
    assert len("太短了") < MIN_MEMBER_BODY_CHARS
    assert distillable_members(session, corpus) == []


def test_adding_the_same_note_twice_is_idempotent(db):
    session, user, account = db
    corpus = _corpus(session, user)
    note = _note(session, user, account, 0)

    first = add_notes_to_set(session, user, corpus, [note.id])
    second = add_notes_to_set(session, user, corpus, [note.id])

    assert first["added"] == 1
    assert second["added"] == 0
    assert second["skipped_already_in_set"] == 1
    assert session.query(CorpusMember).count() == 1


def test_genre_is_never_guessed(db):
    session, user, account = db
    corpus = _corpus(session, user)
    note = _note(session, user, account, 0)

    add_notes_to_set(session, user, corpus, [note.id])

    member = session.query(CorpusMember).one()
    assert member.genre == "unclassified"


def test_unknown_genre_is_rejected(db):
    session, user, account = db
    corpus = _corpus(session, user)
    note = _note(session, user, account, 0)

    with pytest.raises(CorpusError):
        add_notes_to_set(session, user, corpus, [note.id], genre="日记")


def test_another_users_notes_are_not_added(db):
    session, user, account = db
    corpus = _corpus(session, user)
    other = User(username="members-other", password_hash="x")
    session.add(other)
    session.commit()
    foreign = Note(
        user_id=other.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id="foreign",
        title="别人的",
        content=BODY,
        source_type="discovery",
    )
    session.add(foreign)
    session.commit()

    result = add_notes_to_set(session, user, corpus, [foreign.id])

    assert result["added"] == 0
    assert result["missing_note_ids"] == [foreign.id]
    assert session.query(CorpusMember).count() == 0


def test_cap_reports_how_many_still_fit(db, monkeypatch):
    session, user, account = db
    corpus = _corpus(session, user)
    first = _note(session, user, account, 0)
    add_notes_to_set(session, user, corpus, [first.id])

    import backend.app.services.corpus_service as service

    monkeypatch.setattr(service, "MAX_NOTES_PER_SET", 2)
    extra = [_note(session, user, account, i) for i in range(1, 3)]
    with pytest.raises(CorpusError) as excinfo:
        add_notes_to_set(session, user, corpus, [n.id for n in extra])
    assert "还能加 1 篇" in str(excinfo.value)
    assert MAX_NOTES_PER_SET >= 2


def test_removing_a_member_keeps_the_note_in_the_library(db):
    session, user, account = db
    corpus = _corpus(session, user)
    note = _note(session, user, account, 0)
    add_notes_to_set(session, user, corpus, [note.id])
    member = session.query(CorpusMember).one()

    remove_member(session, user, corpus, member.id)

    assert session.query(CorpusMember).count() == 0
    assert session.query(Note).count() == 1


def test_removing_a_member_from_another_set_is_refused(db):
    session, user, account = db
    first = _corpus(session, user)
    second = _corpus(session, user)
    note = _note(session, user, account, 0)
    add_notes_to_set(session, user, first, [note.id])
    member = session.query(CorpusMember).one()

    with pytest.raises(CorpusError):
        remove_member(session, user, second, member.id)
