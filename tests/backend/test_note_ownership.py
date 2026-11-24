"""笔记归属与粉丝数三态：两个会安静骗人的口径。

Both defects here produced plausible-looking numbers:

* "this account's notes" was implemented four ways; two of them counted 104
  crawled competitor posts as the user's own, so the evolution guard
  ``len >= 10`` was always true and its report said 样本来自当前账号的笔记.
* ``author_fans = 0`` meant both "genuinely zero followers" and "never fetched".
  97 of 104 crawled notes carried the second meaning, and 75 of those had 1,000+
  likes, so every low-follower filter discarded the best samples while reporting
  a confident total.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import Note, PlatformAccount, User
from backend.app.services.note_ownership import (
    OWN_SOURCE_TYPES,
    count_own_notes,
    filter_own,
    is_own_note,
    library_notes,
    own_notes,
)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ownership.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _setup(tmp_path):
    db = _session(tmp_path)
    user = User(username="owner", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="我的号", status="active"
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return db, user, account


def _note(db, user, account, note_id, *, source_type, likes=0, fans=0,
          fans_status="unknown", author_id="", raw=None):
    note = Note(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id=note_id,
        title=f"标题 {note_id}",
        content="正文",
        author_name="作者",
        author_id=author_id,
        source_type=source_type,
        like_count=likes,
        author_fans=fans,
        author_fans_status=fans_status,
        raw_json=raw or {},
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


# --- 归属 -------------------------------------------------------------------


def test_creator_and_publish_are_own_notes(tmp_path):
    db, user, account = _setup(tmp_path)
    try:
        own = _note(db, user, account, "n1", source_type="creator", likes=5)
        published = _note(db, user, account, "n2", source_type="publish", likes=9)

        assert is_own_note(own)
        assert is_own_note(published)
    finally:
        db.close()


def test_discovery_is_never_an_own_note(tmp_path):
    """The bug: crawled posts share platform_account_id with our own."""
    db, user, account = _setup(tmp_path)
    try:
        crawled = _note(db, user, account, "c1", source_type="discovery", likes=76000)

        assert not is_own_note(crawled), (
            "采集笔记绝不能因为 platform_account_id 相同就算成自有"
        )
    finally:
        db.close()


def test_legacy_rows_without_source_type_use_raw_origin(tmp_path):
    db, user, account = _setup(tmp_path)
    try:
        legacy_own = _note(
            db, user, account, "l1", source_type="discovery", raw={"origin": "publish"}
        )
        legacy_creator = _note(
            db, user, account, "l2", source_type="discovery",
            raw={"source": "creator_published"},
        )

        assert is_own_note(legacy_own)
        assert is_own_note(legacy_creator)
    finally:
        db.close()


def test_own_notes_isolates_the_crawled_library(tmp_path):
    """The exact shape of the production database: 4 own + N crawled."""
    db, user, account = _setup(tmp_path)
    try:
        for index in range(4):
            _note(db, user, account, f"own{index}", source_type="creator", likes=index)
        for index in range(20):
            _note(db, user, account, f"lib{index}", source_type="discovery", likes=1000)

        own = own_notes(db, user, account.id)
        library = library_notes(db, user)

        assert len(own) == 4
        assert len(library) == 20
        assert count_own_notes(db, user, account.id) == 4
        assert not set(n.id for n in own) & set(n.id for n in library)
    finally:
        db.close()


def test_evolution_guard_can_no_longer_pass_on_crawled_data(tmp_path):
    """``len >= 10`` used to be trivially true. It must now reflect own notes."""
    db, user, account = _setup(tmp_path)
    try:
        for index in range(4):
            _note(db, user, account, f"own{index}", source_type="creator")
        for index in range(104):
            _note(db, user, account, f"lib{index}", source_type="discovery")

        # The production symptom: 108 notes under one account id, 4 of them ours.
        assert len(own_notes(db, user, account.id)) == 4 < 10, (
            "守卫必须看到真实的 4 篇，而不是 108 篇"
        )
    finally:
        db.close()


def test_filter_own_works_on_loaded_lists(tmp_path):
    db, user, account = _setup(tmp_path)
    try:
        _note(db, user, account, "o1", source_type="creator")
        _note(db, user, account, "l1", source_type="discovery")
        loaded = db.query(Note).all()

        assert len(filter_own(loaded)) == 1
    finally:
        db.close()


# --- 粉丝数三态 -------------------------------------------------------------


def test_new_note_defaults_to_unknown_fans(tmp_path):
    """A note saved before any profile fetch must not claim a follower count."""
    db, user, account = _setup(tmp_path)
    try:
        note = Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id="fresh",
            title="t",
            content="c",
        )
        db.add(note)
        db.commit()
        db.refresh(note)

        assert note.author_fans_status == "unknown"
        assert note.author_fans == 0
    finally:
        db.close()


def test_unknown_fans_is_not_a_zero(tmp_path):
    """The distinction that the old schema could not express."""
    db, user, account = _setup(tmp_path)
    try:
        unknown = _note(
            db, user, account, "u1", source_type="discovery", likes=76000,
            fans=0, fans_status="unknown",
        )
        real_zero = _note(
            db, user, account, "z1", source_type="discovery", likes=12,
            fans=0, fans_status="known",
        )

        assert unknown.author_fans_status != real_zero.author_fans_status
        # Only the fetched one may be judged as "low follower".
        judged = [n for n in (unknown, real_zero) if n.author_fans_status == "known"]
        assert judged == [real_zero]
    finally:
        db.close()


def test_known_with_positive_count_is_the_only_enriched_case(tmp_path):
    db, user, account = _setup(tmp_path)
    try:
        enriched = _note(
            db, user, account, "e1", source_type="discovery", fans=2552,
            fans_status="known",
        )
        unknown = _note(
            db, user, account, "u2", source_type="discovery", fans=0,
            fans_status="unknown",
        )

        candidates = [
            n for n in (enriched, unknown)
            if n.author_fans_status == "known" and n.author_fans > 0
        ]
        assert candidates == [enriched]
    finally:
        db.close()


def test_own_source_types_are_explicit():
    assert OWN_SOURCE_TYPES == ("creator", "publish")
