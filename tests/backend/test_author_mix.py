"""Author-mix detection: an empty rule set must explain itself.

Real symptom: distilling the 104-post topic corpus (100+ authors) reported
0 hard rules with no explanation, which reads as "the distiller is broken".
It was not: the same detectors on 5 posts by one author produce 4 hard rules.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import CorpusMember, CorpusSet, Note, User
from backend.app.services.evidence_distill_service import (
    DistillError,
    author_mix,
    distill_corpus_set,
)


LONG_BODY = (
    "不是A而是B，我觉得其实可以。这里有多少人，写了一个具体的数字，"
    "又有一次具体的时间，那天晚上八点。还有一句原话：「你别急」。"
    "胸口发闷。这就是一个可以核验的细节，让整段话有重量。"
    "所以我后来想明白了，真正的问题不是选择，而是你一直在重复同一种模式。"
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'mix.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="mix-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    try:
        yield session, user
    finally:
        session.close()


def _add_corpus(db, user, authors: list[str], body: str = "不是A而是B，我觉得其实可以。") -> CorpusSet:
    corpus = CorpusSet(user_id=user.id, name="mix", kind="account", status="labelled")
    db.add(corpus)
    db.flush()
    for index, author in enumerate(authors):
        note = Note(
            user_id=user.id,
            platform_account_id=1,
            platform="douyin",
            note_id=f"n{index}",
            title=f"标题{index}",
            content=body,
            author_name=author,
            source_type="discovery",
        )
        db.add(note)
        db.flush()
        db.add(
            CorpusMember(
                set_id=corpus.id,
                user_id=user.id,
                note_id=note.note_id,
                note_db_id=note.id,
                collect_status="ok",
                genre="experience",
                role="baseline",
            )
        )
    db.commit()
    return corpus


def test_single_author_is_detected(db):
    session, user = db
    corpus = _add_corpus(session, user, ["同一人"] * 8)
    mix = author_mix(session, user, corpus)
    assert mix["authors"] == 1
    assert mix["posts"] == 8
    assert mix["single_author"] is True
    assert mix["top_share"] == 1.0


def test_many_authors_is_not_single_author(db):
    session, user = db
    corpus = _add_corpus(session, user, [f"作者{i}" for i in range(12)])
    mix = author_mix(session, user, corpus)
    assert mix["authors"] == 12
    assert mix["single_author"] is False
    assert mix["top_share"] < 0.2


def test_empty_corpus_reports_zero_authors(db):
    session, user = db
    corpus = CorpusSet(user_id=user.id, name="empty", kind="account", status="draft")
    session.add(corpus)
    session.commit()
    mix = author_mix(session, user, corpus)
    assert mix == {"authors": 0, "posts": 0, "top_share": 0.0, "single_author": False}


def test_thin_video_corpus_states_its_volume(db):
    """Ten 40-second clips pass the document count while carrying ~2k chars."""
    session, user = db
    body = "这是一段口播文稿，用来描述一件具体的小事，长度大约几十个字，但离一篇长文还差得很远很远。"
    assert len(body) >= 40
    corpus = CorpusSet(user_id=user.id, name="thin", kind="account", status="labelled")
    session.add(corpus)
    session.flush()
    for index in range(9):
        note = Note(
            user_id=user.id,
            platform_account_id=1,
            platform="douyin",
            note_id=f"t{index}",
            title=f"标题{index}",
            content=body,
            author_name="同一个人",
            source_type="douyin_extract",
        )
        session.add(note)
        session.flush()
        session.add(
            CorpusMember(
                set_id=corpus.id,
                user_id=user.id,
                note_id=note.note_id,
                note_db_id=note.id,
                collect_status="ok",
                genre="opinion",
                role="baseline",
            )
        )
    session.commit()

    profile = distill_corpus_set(session, user, corpus, name="thin")
    payload = profile.profile_json

    assert payload["report"]["corpus"]["chars"] < 6000
    assert "字" in payload["corpus_warning"]
    assert str(payload["report"]["corpus"]["chars"]) in payload["corpus_warning"]


def test_mixed_corpus_is_refused_and_points_at_the_structure_template(db):
    """A multi-author corpus cannot produce a style, so it must not pretend to.

    Measured on this project's data: 147 single-author posts yield 3 hard rules;
    104 posts by 95 authors yield 0 with the same code. Returning a profile with
    zero rules leaves the user unable to tell "this author has no habits" from
    "you picked a corpus shape that cannot answer the question".
    """
    session, user = db
    # 12 different authors, each with a different body → nothing reaches 80%.
    corpus = CorpusSet(user_id=user.id, name="mixed", kind="topic", status="labelled")
    session.add(corpus)
    session.flush()
    bodies = [
        "第一段。第二段。第三段。这里补一句让全文超过四十个字，避免被当成过短语料处理。",
        "不是A而是B。这里有个细节。再多写几个字，让它成为一段可以进入检测的正文内容。",
        "我觉得其实还好。真的。这句也是凑长度的，目的是让每篇都超过四十个字的门槛。",
        "这段话很短，但加上后面这些补充说明之后，也能达到四十个字以上，不会被丢弃。",
        "这是一段没有任何特征的普通文字，用来稀释覆盖率，同时也顺便把长度补到四十个字以上。",
    ]
    for index in range(12):
        note = Note(
            user_id=user.id,
            platform_account_id=1,
            platform="douyin",
            note_id=f"m{index}",
            title=f"标题{index}",
            content=bodies[index % len(bodies)] * 3,
            author_name=f"作者{index}",
            source_type="discovery",
        )
        session.add(note)
        session.flush()
        session.add(
            CorpusMember(
                set_id=corpus.id,
                user_id=user.id,
                note_id=note.note_id,
                note_db_id=note.id,
                collect_status="ok",
                genre="experience",
                role="baseline",
            )
        )
    session.commit()

    with pytest.raises(DistillError) as excinfo:
        distill_corpus_set(session, user, corpus, name="mixed")

    message = str(excinfo.value)
    assert "12 位作者" in message
    assert "结构模板" in message, "拒绝时必须指出该用哪个工具"


def test_single_author_corpus_still_distils(db):
    """The refusal must be specific to multi-author corpora."""
    session, user = db
    corpus = _add_corpus(session, user, ["同一个人"] * 12, body=LONG_BODY * 6)
    profile = distill_corpus_set(session, user, corpus, name="single")
    payload = profile.profile_json
    assert payload["author_mix"]["single_author"] is True
    assert "位作者" not in (payload.get("corpus_warning") or ""), (
        "单作者语料不该出现「N 位作者」那条拒绝理由"
    )
