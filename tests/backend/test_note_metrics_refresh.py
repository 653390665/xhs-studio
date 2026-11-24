"""Automatic metric refresh for own published notes (no network)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.app.models  # noqa: F401
from backend.app.core.database import Base
from backend.app.core.security import encrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import AccountCookieVersion, Note, PlatformAccount, User
from backend.app.services.note_metrics_refresh_service import (
    due_own_notes,
    refresh_due_own_notes_for_user,
)


class _FakeAdapter:
    def __init__(self, cookies: str) -> None:
        self.cookies = cookies

    def get_note_info(self, url: str):
        return True, "", {
            "data": {
                "items": [
                    {
                        "note_card": {
                            "note_id": "note-1",
                            "display_title": "刷新后的标题",
                            "desc": "刷新后的正文",
                            "interact_info": {
                                "liked_count": "12",
                                "collected_count": "3",
                                "comment_count": "1",
                                "share_count": "0",
                            },
                            "user": {"nickname": "作者", "user_id": "author-1"},
                            "image_list": [],
                        }
                    }
                ]
            }
        }


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="metrics-user", password_hash="x")
    session.add(user)
    session.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        nickname="测试账号",
        status="active",
    )
    session.add(account)
    session.flush()
    session.add(
        AccountCookieVersion(
            platform_account_id=account.id,
            encrypted_cookies=encrypt_text("a=b"),
        )
    )
    session.commit()
    session.refresh(user)
    session.refresh(account)
    try:
        yield session, user, account
    finally:
        session.close()


def _note(
    user: User,
    account: PlatformAccount,
    note_id: str,
    source_type: str,
    *,
    fetched_at=None,
) -> Note:
    return Note(
        user_id=user.id,
        platform_account_id=account.id,
        platform="xhs",
        note_id=note_id,
        title="旧标题",
        content="旧正文",
        source_type=source_type,
        metrics_fetched_at=fetched_at,
    )


def test_due_own_notes_only_selects_stale_own_notes(db):
    session, user, account = db
    now = shanghai_now()
    session.add_all(
        [
            _note(user, account, "own-new", "publish", fetched_at=None),
            _note(user, account, "own-fresh", "creator", fetched_at=now),
            _note(user, account, "own-stale", "publish", fetched_at=now - timedelta(days=2)),
            _note(user, account, "sample-stale", "discovery", fetched_at=None),
        ]
    )
    session.commit()

    due = due_own_notes(session, user, limit=10, now=now)
    ids = {note.note_id for note in due}

    assert "own-new" in ids
    assert "own-stale" in ids
    assert "own-fresh" not in ids
    assert "sample-stale" not in ids


def test_refresh_due_own_notes_updates_metrics_and_memory(db):
    session, user, account = db
    session.add(_note(user, account, "note-1", "publish", fetched_at=None))
    session.commit()

    result = refresh_due_own_notes_for_user(
        session,
        user,
        adapter_factory=_FakeAdapter,
    )

    assert result["updated"] == 1
    note = session.query(Note).filter(Note.note_id == "note-1").one()
    assert note.title == "刷新后的标题"
    assert note.like_count == 12
    assert note.collect_count == 3
    assert note.comment_count == 1
    assert note.metrics_fetched_at is not None
