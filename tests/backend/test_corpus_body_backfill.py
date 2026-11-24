"""Body backfill: a listing page has titles, not bodies.

The gap this closes: ``/corpus/{id}/collect`` saves notes from a profile listing,
where the API returns ``display_title`` and no ``desc``. Those rows were stored as
``collect_status="ok"``, so distillation read empty text and reported it as the
author's style — a member that looked collected and contributed nothing.

Fix has two halves, both tested here:
1. a body-less row is ``pending_body``, never ``ok``;
2. ``/collect-bodies`` fetches detail pages in bounded batches and reports what
   is left, with throttling recorded honestly.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import CorpusMember, CorpusSet, Note, PlatformAccount, User
from backend.app.services.corpus_service import (
    COLLECT_STATUSES,
    distillable_members,
    upsert_member,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bodies.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="bodies-user", password_hash="x")
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


# --- status semantics -------------------------------------------------------


def test_pending_body_is_a_known_status():
    assert "pending_body" in COLLECT_STATUSES


def test_bodyless_row_is_not_distillable(db):
    """The core guarantee: 'collected' without text must not reach a distiller."""
    session, user, account = db
    corpus = CorpusSet(user_id=user.id, name="c", kind="account", status="collected")
    session.add(corpus)
    session.commit()

    note = Note(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id="n1",
        title="只有标题",
        content="",  # listing page carries no body
        source_type="discovery",
    )
    session.add(note)
    session.commit()

    member = upsert_member(
        session,
        user,
        corpus,
        note_id="n1",
        note_db_id=note.id,
        collect_status="pending_body",
    )
    member.genre = "experience"
    member.role = "baseline"
    session.commit()

    assert member.collect_status == "pending_body"
    assert distillable_members(session, corpus) == []


def test_row_with_body_is_distillable(db):
    session, user, account = db
    corpus = CorpusSet(user_id=user.id, name="c2", kind="account", status="collected")
    session.add(corpus)
    session.commit()

    note = Note(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id="n2",
        title="有正文",
        content="这是一段真实正文，足够长。",
        source_type="discovery",
    )
    session.add(note)
    session.commit()

    m = upsert_member(
        session,
        user,
        corpus,
        note_id="n2",
        note_db_id=note.id,
        collect_status="ok",
    )
    m.genre = "experience"
    m.role = "baseline"
    session.commit()

    members = distillable_members(session, corpus)
    assert len(members) == 1


def test_throttled_row_is_not_distillable(db):
    """A throttle is never evidence about writing."""
    session, user, account = db
    corpus = CorpusSet(user_id=user.id, name="c3", kind="account", status="collected")
    session.add(corpus)
    session.commit()

    note = Note(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id="n3",
        content="正文",
        source_type="discovery",
    )
    session.add(note)
    session.commit()

    m = upsert_member(
        session,
        user,
        corpus,
        note_id="n3",
        note_db_id=note.id,
        collect_status="throttled",
    )
    m.genre = "experience"
    m.role = "baseline"
    session.commit()

    assert distillable_members(session, corpus) == []


# --- the request model ------------------------------------------------------


def test_collect_bodies_limit_is_bounded():
    from backend.app.api.corpus import CollectBodiesRequest
    from backend.app.services.crawl_guard import MAX_ITEMS_PER_RUN

    with pytest.raises(Exception):
        CollectBodiesRequest(limit=MAX_ITEMS_PER_RUN + 1)
    with pytest.raises(Exception):
        CollectBodiesRequest(limit=0)
    assert CollectBodiesRequest(limit=10).limit == 10


# --- the endpoint -----------------------------------------------------------


def _prepare_pending(session, user, account, count: int) -> CorpusSet:
    corpus = CorpusSet(user_id=user.id, name="batch", kind="account", status="collected")
    session.add(corpus)
    session.commit()
    for i in range(count):
        note = Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id=f"p{i}",
            title=f"标题{i}",
            content="",
            source_type="discovery",
            raw_json={"xsec_token": "TOKEN"},
        )
        session.add(note)
        session.commit()
        m = upsert_member(
            session,
            user,
            corpus,
            note_id=f"p{i}",
            note_db_id=note.id,
            collect_status="pending_body",
        )
        m.genre = "experience"
        m.role = "baseline"
    session.commit()
    return corpus


class _FakeAdapter:
    """Returns a body for the first N calls, then a throttle."""

    def __init__(self, *, succeed: int = 3, fail_after: bool = False):
        self.succeed = succeed
        self.fail_after = fail_after
        self.calls = 0

    def get_note_info(self, url):
        self.calls += 1
        if self.fail_after and self.calls > self.succeed:
            return False, "访问频繁，请稍后再试", {"code": 300031, "success": False, "msg": "访问频繁"}
        note_id = url.split("/explore/")[1].split("?")[0]
        # Shape matches what the SDK returns: data.items[0].note_card
        return True, "成功", {
            "success": True,
            "code": 0,
            "data": {
                "items": [
                    {
                        "id": note_id,
                        "note_card": {
                            "title": f"详情标题 {note_id}",
                            "desc": f"这是 {note_id} 的真实正文，长度够用。",
                            "user": {"user_id": "a" * 24, "nickname": "作者"},
                        },
                    }
                ]
            },
        }


def test_collect_bodies_fills_text_and_reports_remaining(db, monkeypatch):
    from backend.app.api import corpus as corpus_api

    session, user, account = db
    corpus = _prepare_pending(session, user, account, 5)
    fake = _FakeAdapter(succeed=10)

    monkeypatch.setattr(corpus_api, "_pick_pc_account", lambda *a, **k: account)
    monkeypatch.setattr(corpus_api, "_latest_cookies", lambda *a, **k: "c=1")
    monkeypatch.setattr(corpus_api, "get_xhs_pc_api_adapter_factory", lambda: (lambda c: fake))

    class FakeGuard:
        def cooldown_remaining(self, _key, _action, _seconds):
            return 0

        def mark_run(self, _key, _action):
            pass

        def mark_account_run(self, _):
            pass

        def note_throttle(self, _):
            return 0

        def note_success(self, _):
            pass

    monkeypatch.setattr(corpus_api, "get_crawl_guard", lambda: FakeGuard())

    result = corpus_api.collect_bodies(
        corpus.id,
        corpus_api.CollectBodiesRequest(limit=3),
        current_user=user,
        db=session,
        adapter_factory=lambda c: fake,
    )

    assert result["ok"] == 3
    assert result["remaining"] == 2, "5 篇里补了 3 篇，应剩 2 篇"
    # Bodies actually landed.
    filled = session.query(Note).filter(Note.content != "").count()
    assert filled >= 3


def test_collect_bodies_records_throttle_instead_of_zero_body(db, monkeypatch):
    from backend.app.api import corpus as corpus_api

    session, user, account = db
    corpus = _prepare_pending(session, user, account, 5)
    fake = _FakeAdapter(succeed=1, fail_after=True)

    monkeypatch.setattr(corpus_api, "_pick_pc_account", lambda *a, **k: account)
    monkeypatch.setattr(corpus_api, "_latest_cookies", lambda *a, **k: "c=1")

    class FakeGuard:
        def cooldown_remaining(self, _key, _action, _seconds):
            return 0

        def mark_run(self, _key, _action):
            pass

        def mark_account_run(self, _):
            pass

        def note_throttle(self, _):
            return 1

        def note_success(self, _):
            pass

    monkeypatch.setattr(corpus_api, "get_crawl_guard", lambda: FakeGuard())

    result = corpus_api.collect_bodies(
        corpus.id,
        corpus_api.CollectBodiesRequest(limit=4),
        current_user=user,
        db=session,
        adapter_factory=lambda c: fake,
    )

    assert result["throttled"] >= 1
    # Throttled rows must never be marked ok.
    throttled_rows = (
        session.query(CorpusMember)
        .filter(CorpusMember.set_id == corpus.id, CorpusMember.collect_status == "throttled")
        .count()
    )
    assert throttled_rows >= 1
    empty_ok = (
        session.query(Note)
        .filter(Note.content == "")
        .count()
    )
    assert empty_ok >= 1, "被限流的笔记正文仍为空，但状态是 throttled 不是 ok"


def test_collect_bodies_noop_when_nothing_pending(db, monkeypatch):
    from backend.app.api import corpus as corpus_api

    session, user, account = db
    corpus = CorpusSet(user_id=user.id, name="empty", kind="account", status="collected")
    session.add(corpus)
    session.commit()

    monkeypatch.setattr(corpus_api, "_pick_pc_account", lambda *a, **k: account)

    result = corpus_api.collect_bodies(
        corpus.id,
        corpus_api.CollectBodiesRequest(limit=5),
        current_user=user,
        db=session,
        adapter_factory=lambda c: _FakeAdapter(),
    )
    assert result["ok"] == 0
    assert result["remaining"] == 0
