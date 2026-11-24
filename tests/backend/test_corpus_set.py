"""对标集：可比性、反例成立条件、风控失败不变成数据。

The tests here encode the measured failures that motivated the feature:

* 97 of 104 crawled notes had ``author_fans = 0`` which was "not collected", not
  "zero followers" — so ``collect_status`` must exist and distillation must read
  only ``ok``;
* the event genre sits at ~96 median likes against 2,239–3,909 for other genres,
  so comparing across genres turns routine announcements into "bad writing";
* a genre with two notes makes every note either the best or the worst.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import CorpusMember, CorpusSet, Note, PlatformAccount, User
from backend.app.services.corpus_service import (
    MIN_BASELINE_PER_GENRE,
    CorpusError,
    assign_roles,
    create_set,
    distillable_members,
    serialize_set,
    set_genre,
    upsert_member,
)
from backend.app.services.crawl_guard import (
    CrawlGuard,
    classify_failure,
    looks_throttled,
)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'corpus.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _user_account(db, name="corpus-user"):
    user = User(username=name, password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="测试号", status="active"
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return user, account


def _note(db, user, account, note_id, likes, collects=0, comments=0, shares=0):
    note = Note(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id=note_id,
        title=f"标题 {note_id}",
        content="正文内容",
        author_name="作者",
        source_type="discovery",
        like_count=likes,
        collect_count=collects,
        comment_count=comments,
        share_count=shares,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


# --- 建集 -------------------------------------------------------------------


def test_account_set_requires_a_source(tmp_path):
    db = _session(tmp_path)
    try:
        user, _ = _user_account(db)
        try:
            create_set(db, user, name="空账号集", kind="account")
            assert False, "an account set with no source must be rejected"
        except CorpusError as exc:
            assert "账号主页链接" in str(exc)
    finally:
        db.close()


def test_topic_set_requires_a_keyword(tmp_path):
    db = _session(tmp_path)
    try:
        user, _ = _user_account(db)
        try:
            create_set(db, user, name="空话题集", kind="topic")
            assert False, "a topic set with no keyword must be rejected"
        except CorpusError as exc:
            assert "关键词" in str(exc)
    finally:
        db.close()


def test_unknown_kind_is_rejected(tmp_path):
    db = _session(tmp_path)
    try:
        user, _ = _user_account(db)
        try:
            create_set(db, user, name="x", kind="mixed", keyword="ai")
            assert False, "a mixed set would blend tone with effectiveness"
        except CorpusError:
            pass
    finally:
        db.close()


# --- 风控失败不能变成数据 -----------------------------------------------------


def test_throttled_member_is_excluded_from_distillation(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _user_account(db)
        corpus = create_set(db, user, name="集", kind="account", source_accounts=["u1"])
        note = _note(db, user, account, "n1", likes=100)
        upsert_member(db, user, corpus, note_id="n1", note_db_id=note.id, collect_status="ok")
        upsert_member(
            db, user, corpus, note_id="n2", collect_status="throttled", collect_error="429"
        )
        set_genre(db, user, [m.id for m in db.query(CorpusMember).all()], "experience")

        usable = distillable_members(db, corpus)
        # Only the collected one survives, and only after roles are assigned.
        assert all(member.collect_status == "ok" for member in usable)
        assert all(member.note_id != "n2" for member in usable)
    finally:
        db.close()


def test_failed_collection_never_creates_a_note(tmp_path):
    """The whole point: a throttle must not look like a zero-like note."""
    db = _session(tmp_path)
    try:
        user, _ = _user_account(db)
        corpus = create_set(db, user, name="集", kind="account", source_accounts=["u1"])
        upsert_member(
            db, user, corpus, note_id="n-throttled", collect_status="throttled", collect_error="461"
        )

        assert db.query(Note).count() == 0
        counts = serialize_set(db, corpus)["collect"]
        assert counts["throttled"] == 1
        assert counts["ok"] == 0
    finally:
        db.close()


# --- 反例只在同体裁内成立 -----------------------------------------------------


def _build_genre(db, user, account, corpus, genre, engagement_values):
    ids = []
    for index, value in enumerate(engagement_values):
        note = _note(db, user, account, f"{genre}-{index}", likes=value)
        member = upsert_member(
            db, user, corpus, note_id=note.note_id, note_db_id=note.id, collect_status="ok"
        )
        ids.append(member.id)
    set_genre(db, user, ids, genre)
    return ids


def test_event_genre_is_not_compared_against_experience_genre(tmp_path):
    """A 0-like event notice must not become "bad copywriting" evidence.

    Measured on the real library: event genre median 96 likes, others 2,239–3,909.
    """
    db = _session(tmp_path)
    try:
        user, account = _user_account(db)
        corpus = create_set(db, user, name="集", kind="account", source_accounts=["u1"])

        # Experience posts: 1000, 2000, 3000 -> median 2000
        _build_genre(db, user, account, corpus, "experience", [1000, 2000, 3000])
        # Event posts: 10, 20, 30 -> median 20. Much lower, but that is the genre.
        _build_genre(db, user, account, corpus, "event", [10, 20, 30])

        report = assign_roles(db, user, corpus)

        assert report["genres"]["experience"]["median_engagement"] == 2000
        assert report["genres"]["event"]["median_engagement"] == 20
        # Each genre produced its own baseline/negative, not a global split.
        assert report["genres"]["experience"]["baseline"] == 1
        assert report["genres"]["event"]["baseline"] == 1
    finally:
        db.close()


def test_unclassified_members_are_excluded_and_counted(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _user_account(db)
        corpus = create_set(db, user, name="集", kind="account", source_accounts=["u1"])
        _build_genre(db, user, account, corpus, "experience", [100, 200, 300])
        # Three more, left unclassified on purpose.
        for index in range(3):
            note = _note(db, user, account, f"raw-{index}", likes=50)
            upsert_member(
                db, user, corpus, note_id=note.note_id, note_db_id=note.id, collect_status="ok"
            )

        report = assign_roles(db, user, corpus)

        assert report["skipped_unclassified"] == 3
        assert "unclassified" not in report["genres"]
        # Nothing was guessed into a genre.
        untouched = db.query(CorpusMember).filter(CorpusMember.genre == "unclassified").all()
        assert len(untouched) == 3
        assert all(member.role == "unassigned" for member in untouched)
    finally:
        db.close()


def test_small_genre_gets_no_roles(tmp_path):
    """Two notes would make one "the best" and one "the worst"; that is not evidence."""
    db = _session(tmp_path)
    try:
        user, account = _user_account(db)
        corpus = create_set(db, user, name="集", kind="account", source_accounts=["u1"])
        _build_genre(db, user, account, corpus, "list", [100, 500])

        report = assign_roles(db, user, corpus)

        assert report["genres"]["list"]["skipped"] == "样本不足"
        roles = {m.role for m in db.query(CorpusMember).all()}
        assert roles == {"unassigned"}
    finally:
        db.close()


def test_median_value_is_neutral_not_negative(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _user_account(db)
        corpus = create_set(db, user, name="集", kind="account", source_accounts=["u1"])
        # median of [100, 200, 300] is 200
        _build_genre(db, user, account, corpus, "experience", [100, 200, 300])

        assign_roles(db, user, corpus)

        middle = db.query(CorpusMember).filter(CorpusMember.note_id == "experience-1").one()
        assert middle.role == "neutral", "a note exactly at the median proves nothing"
    finally:
        db.close()


def test_changing_genre_clears_the_old_role(tmp_path):
    db = _session(tmp_path)
    try:
        user, account = _user_account(db)
        corpus = create_set(db, user, name="集", kind="account", source_accounts=["u1"])
        ids = _build_genre(db, user, account, corpus, "experience", [100, 200, 300])
        assign_roles(db, user, corpus)
        assert any(m.role == "baseline" for m in db.query(CorpusMember).all())

        set_genre(db, user, ids, "event")

        assert all(m.role == "unassigned" for m in db.query(CorpusMember).all()), (
            "a role computed under the old genre would silently survive relabelling"
        )
    finally:
        db.close()


# --- 风控护栏 ---------------------------------------------------------------


def test_throttle_messages_are_classified_as_throttled():
    assert looks_throttled("Client error '429 Too Many Requests'")
    assert classify_failure("461") == "throttled"
    assert classify_failure("操作过于频繁") == "throttled"


def test_deleted_note_is_not_throttled():
    assert classify_failure("404 not found") == "deleted"


def test_account_cooldown_blocks_an_immediate_second_run():
    guard = CrawlGuard()
    guard.mark_account_run(42)
    assert guard.account_cooldown_remaining(42) > 0
    assert guard.account_cooldown_remaining(43) == 0


def test_three_consecutive_throttles_abort_the_run():
    guard = CrawlGuard()
    guard.note_throttle(1)
    guard.note_throttle(1)
    assert not guard.should_abort(1)
    guard.note_throttle(1)
    assert guard.should_abort(1)
    # A success resets the streak.
    guard.note_success(1)
    assert not guard.should_abort(1)


def test_action_budget_is_per_action_not_global():
    guard = CrawlGuard()
    # profile_page allows 2/min; those calls must not consume the detail budget.
    assert guard.allow(1, "profile_page")
    assert guard.allow(1, "profile_page")
    assert not guard.allow(1, "profile_page")
    assert guard.allow(1, "note_detail")
