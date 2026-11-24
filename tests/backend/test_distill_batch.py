"""Distilled batches: prompt context that used to live only in the browser.

Regression background (measured on the real project):

* a "batch" was ``localStorage["xhs.studio.results.<id>"]``; clearing site data
  lost it, and the writing page's picker went empty with no error;
* ``skill_ids`` did not exist, so picking 10 skills injected 3 (the routing
  default) and said nothing about the other 7;
* ``ai_drafts`` had no way to answer "which style / template / batch produced
  this", which makes every later comparison unanswerable;
* ``draft-chat`` built its history from the request payload only, so a page
  reload made the model forget the conversation it had just had.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import SkillLibraryItem, User
from backend.app.services.distill_batch_service import (
    DistillBatchError,
    batch_reference_text,
    get_batch,
    list_batches,
    serialize_batch,
    upsert_batch,
)
from backend.app.services.skill_library_service import (
    MAX_EXPLICIT_SKILLS,
    module_skill_text,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'batch.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="batch-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    try:
        yield session, user
    finally:
        session.close()


def _items(full="正文模板", title="标题模板"):
    return [
        {"kind": "full", "title": "整篇", "body": full},
        {"kind": "title", "title": "标题", "body": title},
    ]


# --- batch storage -----------------------------------------------------------


def test_batch_round_trip_keeps_the_four_kinds(db):
    session, user = db
    record = upsert_batch(
        session, user, batch_id="b-1", name="第一批", items=_items()
    )
    payload = serialize_batch(session, record)
    assert [item["kind"] for item in payload["items"]] == ["full", "title"]
    assert payload["kinds"] == ["full", "title"]
    assert payload["meta"]["client_id"] == "b-1"


def test_saving_the_same_client_id_updates_instead_of_duplicating(db):
    session, user = db
    first = upsert_batch(session, user, batch_id="b-1", name="旧名", items=_items())
    second = upsert_batch(
        session, user, batch_id="b-1", name="新名", items=_items(full="改过的正文")
    )
    assert first.id == second.id
    assert len(list_batches(session, user)) == 1
    assert batch_reference_text(session, second) == "改过的正文\n\n标题模板"


def test_two_batches_without_ids_are_two_rows(db):
    session, user = db
    upsert_batch(session, user, batch_id=None, name="A", items=_items())
    upsert_batch(session, user, batch_id=None, name="B", items=_items())
    assert len(list_batches(session, user)) == 2


def test_duplicate_kind_is_rejected(db):
    session, user = db
    with pytest.raises(DistillBatchError):
        upsert_batch(
            session,
            user,
            batch_id=None,
            name="bad",
            items=[
                {"kind": "full", "body": "a"},
                {"kind": "full", "body": "b"},
            ],
        )


def test_unknown_kind_is_rejected(db):
    session, user = db
    with pytest.raises(DistillBatchError):
        upsert_batch(
            session, user, batch_id=None, name="bad", items=[{"kind": "outline", "body": "a"}]
        )


def test_another_users_batch_is_not_readable(db):
    session, user = db
    other = User(username="other-user", password_hash="x")
    session.add(other)
    session.commit()
    record = upsert_batch(session, user, batch_id="b-1", name="mine", items=_items())
    with pytest.raises(DistillBatchError):
        get_batch(session, other, record.id)


# --- explicit skill ids ------------------------------------------------------


def _skill(db, user, name, body, module="draft", enabled=True):
    item = SkillLibraryItem(
        user_id=user.id,
        slug=name.lower(),
        name=name,
        module=module,
        content_md=body,
        enabled=enabled,
    )
    db.add(item)
    db.commit()
    return item


def test_explicit_skill_ids_inject_exactly_those(db):
    session, user = db
    picked = _skill(session, user, "选中的", "这条应该出现")
    other = _skill(session, user, "没选的", "这条不该出现")
    text = module_skill_text(
        session, user, "draft", skill_ids=[picked.id], account_id=None
    )
    assert "这条应该出现" in text
    assert "这条不该出现" not in text
    assert other.id != picked.id


def test_disabled_skill_is_reported_not_silently_dropped(db):
    session, user = db
    off = _skill(session, user, "停用的", "停用正文", enabled=False)
    text = module_skill_text(session, user, "draft", skill_ids=[off.id], account_id=None)
    assert "都不可用" in text


def test_partially_unavailable_skills_say_how_many_were_dropped(db):
    session, user = db
    on = _skill(session, user, "可用", "可用正文")
    off = _skill(session, user, "停用", "停用正文", enabled=False)
    text = module_skill_text(
        session, user, "draft", skill_ids=[on.id, off.id], account_id=None
    )
    assert "可用正文" in text
    assert "1 篇勾选的 Skill 不可用" in text


def test_no_skill_ids_keeps_automatic_routing(db):
    session, user = db
    _skill(session, user, "自动", "自动命中的正文")
    text = module_skill_text(session, user, "draft", query="写一篇", account_id=None)
    assert "自动命中的正文" in text


def test_explicit_skill_cap_is_sane():
    assert 5 <= MAX_EXPLICIT_SKILLS <= 50
