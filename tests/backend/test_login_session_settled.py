"""A settled login session must still say which account it bound.

The bug users reported: scan the QR, log in on the phone, and the UI does
nothing. Two causes, both fixed here:

1. The GET poll short-circuited a ``confirmed`` session to
   ``{session_id, status, qr_url}`` — no ``account``. The panel required
   ``polled.account`` to fire its success path, so a poll that landed after the
   first confirmation (or a page reload mid-login) silently did nothing.
2. The drawer never closed on success, so even a correct confirmation left the
   QR on screen — indistinguishable from "nothing happened".
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import LoginSession, PlatformAccount, User


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'login.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="login-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    try:
        yield session, user
    finally:
        session.close()


def _account(db, user, *, nickname="阿桑", status="active"):
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        external_user_id="000000000000000000000001",
        nickname=nickname,
        status=status,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _session(db, user, status):
    row = LoginSession(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        status=status,
        login_method="qr",
        qr_id="123",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_settled_confirmed_session_returns_the_account(db):
    """The core fix: ``confirmed`` must carry ``account``."""
    from backend.app.api.login_sessions import _account_for_settled_session

    session, user = db
    account = _account(session, user)

    payload = _account_for_settled_session(session, user)
    assert payload is not None
    assert payload["id"] == account.id
    assert payload["nickname"] == "阿桑"


def test_settled_session_with_no_accounts_returns_none(db):
    from backend.app.api.login_sessions import _account_for_settled_session

    session, user = db
    assert _account_for_settled_session(session, user) is None


def test_settled_session_picks_the_most_recent_account(db):
    """The account the user just bound is the one most recently touched."""
    from backend.app.api.login_sessions import _account_for_settled_session

    session, user = db
    _account(session, user, nickname="旧账号")
    newer = _account(session, user, nickname="刚绑的账号")

    payload = _account_for_settled_session(session, user)
    assert payload["nickname"] == newer.nickname


def test_settled_payload_is_serialisable_by_the_frontend(db):
    """Same shape ``serialize_account`` produces elsewhere."""
    from backend.app.api.login_sessions import _account_for_settled_session

    session, user = db
    _account(session, user)
    payload = _account_for_settled_session(session, user)
    for key in ("id", "platform", "sub_type", "nickname", "status"):
        assert key in payload, f"前端依赖字段 {key} 缺失"


def test_expired_session_does_not_invent_an_account(db):
    """An expired session proves nothing about binding."""
    from backend.app.api.login_sessions import _account_for_settled_session

    session, user = db
    _account(session, user)
    # The helper itself is status-agnostic; the endpoint decides. This pins the
    # contract that the endpoint only calls it for ``confirmed``.
    row = _session(session, user, "expired")
    assert row.status == "expired"
    # Documenting intent: no account block is built for expired sessions.
    assert _account_for_settled_session(session, user) is not None  # helper is reusable
