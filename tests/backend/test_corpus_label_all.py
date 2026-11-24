"""Set-level genre labelling must prove the set is homogeneous first.

Genre is human-assigned by design (`corpus_service` says why). But labelling 150
notes one at a time is not a workflow anyone finishes, so the gap is real. The
honest way to close it is a set-level label guarded by evidence, not a per-note
guess:

* refuse when the set mixes formats (that is exactly what genre protects against)
* show the numbers so "it's homogeneous" can be checked, not trusted
* support a dry run so the UI can ask before writing
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import CorpusMember, CorpusSet, Note, PlatformAccount, User
from backend.app.services.corpus_service import upsert_member


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'homo.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="homo-user", password_hash="x")
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


def _build(db, user, account, posts: list[tuple[str, str]]):
    corpus = CorpusSet(user_id=user.id, name="h", kind="account", status="collected")
    db.add(corpus)
    db.commit()
    for index, (title, body) in enumerate(posts):
        note = Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id=f"n{index}",
            title=title,
            content=body,
            source_type="discovery",
        )
        db.add(note)
        db.commit()
        upsert_member(
            db,
            user,
            corpus,
            note_id=f"n{index}",
            note_db_id=note.id,
            collect_status="ok",
        )
    db.commit()
    return corpus


HOMOGENEOUS = [
    (f"每天拆解一个AI产品：P{i}", f"这是第 {i} 个产品的拆解，正文是叙述性的判断。")
    for i in range(12)
]

MIXED = [
    (f"每天拆解一个AI产品：P{i}", "产品拆解正文。")
    for i in range(6)
] + [
    (f"宁波线下沙龙第{i}期", "活动时间：周六下午两点，地点：鄞州，扫码报名，名额有限。")
    for i in range(6)
]


def test_homogeneous_corpus_is_detected(db):
    from backend.app.api.corpus import _homogeneity_report

    session, user, account = db
    corpus = _build(session, user, account, HOMOGENEOUS)
    report = _homogeneity_report(session, corpus)
    assert report["homogeneous"] is True, report
    assert report["prefix_share"] >= 0.5
    assert report["event_recruit_share"] == 0.0


def test_mixed_corpus_is_rejected_with_a_reason(db):
    from backend.app.api.corpus import _homogeneity_report

    session, user, account = db
    corpus = _build(session, user, account, MIXED)
    report = _homogeneity_report(session, corpus)
    assert report["homogeneous"] is False
    assert "活动" in report["reason"] or "招募" in report["reason"]


def test_numbered_lists_are_not_folded_into_prose(db):
    from backend.app.api.corpus import _homogeneity_report

    session, user, account = db
    posts = [
        (f"每天拆解一个AI产品：P{i}", "1. 第一点\n2. 第二点\n3. 第三点\n4. 第四点")
        for i in range(10)
    ]
    corpus = _build(session, user, account, posts)
    report = _homogeneity_report(session, corpus)
    assert report["list_share"] > 0.3
    assert report["homogeneous"] is False


def test_label_all_refuses_a_mixed_set(db):
    from backend.app.api.corpus import LabelAllRequest, label_all_members

    session, user, account = db
    corpus = _build(session, user, account, MIXED)
    with pytest.raises(Exception) as exc:
        label_all_members(
            corpus.id,
            LabelAllRequest(genre="opinion", confirm=True),
            current_user=user,
            db=session,
        )
    assert "不能整集标注" in str(exc.value)


def test_label_all_dry_run_writes_nothing(db):
    from backend.app.api.corpus import LabelAllRequest, label_all_members

    session, user, account = db
    corpus = _build(session, user, account, HOMOGENEOUS)
    result = label_all_members(
        corpus.id,
        LabelAllRequest(genre="opinion", confirm=False),
        current_user=user,
        db=session,
    )
    assert result["dry_run"] is True
    assert result["would_update"] == 12
    remaining = (
        session.query(CorpusMember)
        .filter(CorpusMember.set_id == corpus.id, CorpusMember.genre == "unclassified")
        .count()
    )
    assert remaining == 12, "试运行不能写库"


def test_label_all_confirmed_writes_the_genre(db):
    from backend.app.api.corpus import LabelAllRequest, label_all_members

    session, user, account = db
    corpus = _build(session, user, account, HOMOGENEOUS)
    result = label_all_members(
        corpus.id,
        LabelAllRequest(genre="opinion", confirm=True),
        current_user=user,
        db=session,
    )
    session.commit()
    assert result["updated"] == 12
    labelled = (
        session.query(CorpusMember)
        .filter(CorpusMember.set_id == corpus.id, CorpusMember.genre == "opinion")
        .count()
    )
    assert labelled == 12


def test_label_all_rejects_unclassified(db):
    from backend.app.api.corpus import LabelAllRequest, label_all_members

    session, user, account = db
    corpus = _build(session, user, account, HOMOGENEOUS)
    with pytest.raises(Exception):
        label_all_members(
            corpus.id,
            LabelAllRequest(genre="unclassified", confirm=True),
            current_user=user,
            db=session,
        )
