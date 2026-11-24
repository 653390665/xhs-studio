"""Stored cookies are JSON; the SDK needs a ``Cookie`` header.

The failure this pins: QR login stores cookies as a JSON object, but
``XHSPcApiAdapter`` passes them to ``XHSPcAuth``, which parses a header string.
Calling the SDK with the raw JSON produced

    XHSPcAuth.cookies must contain a1

even though ``a1`` was in the object — right value, wrong shape. Six of seven
cookie readers normalised; ``api/corpus.py`` did not, so列表采集 worked only
for logins that happened to store a header string.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.security import encrypt_text
from backend.app.models import AccountCookieVersion, PlatformAccount, User
from backend.app.services.account_cookies import cookies_to_string, latest_cookies

JSON_COOKIES = json.dumps(
    {"a1": "abc123", "web_session": "def456", "gid": "xyz"}, ensure_ascii=False
)
HEADER_COOKIES = "a1=abc123; web_session=def456"


# --- normalisation ----------------------------------------------------------


def test_json_cookies_become_a_header():
    assert cookies_to_string(JSON_COOKIES) == "a1=abc123; web_session=def456; gid=xyz"


def test_header_cookies_pass_through():
    assert cookies_to_string(HEADER_COOKIES) == HEADER_COOKIES


def test_empty_input_stays_empty():
    assert cookies_to_string("") == ""
    assert cookies_to_string("   ") == ""


def test_malformed_json_is_returned_as_is():
    broken = "{not really json"
    assert cookies_to_string(broken) == broken


def test_normalised_value_contains_a1():
    """The specific key the SDK complains about."""
    assert "a1=" in cookies_to_string(JSON_COOKIES)


# --- the shared accessor ----------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cookies.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(username="cookie-user", password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="号", status="active"
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    try:
        yield session, account
    finally:
        session.close()


def test_latest_cookies_normalises_the_stored_json(db):
    session, account = db
    session.add(
        AccountCookieVersion(
            platform_account_id=account.id, encrypted_cookies=encrypt_text(JSON_COOKIES)
        )
    )
    session.commit()

    value = latest_cookies(session, account)
    assert value.startswith("a1=abc123"), value
    assert "{" not in value, "返回给 SDK 的不能还是 JSON"


def test_latest_cookies_picks_the_newest_version(db):
    session, account = db
    session.add(
        AccountCookieVersion(
            platform_account_id=account.id, encrypted_cookies=encrypt_text(HEADER_COOKIES)
        )
    )
    session.commit()
    session.add(
        AccountCookieVersion(
            platform_account_id=account.id, encrypted_cookies=encrypt_text(JSON_COOKIES)
        )
    )
    session.commit()

    assert "a1=abc123" in latest_cookies(session, account)


def test_missing_cookie_raises_lookuperror(db):
    session, account = db
    with pytest.raises(LookupError):
        latest_cookies(session, account)


def test_accepts_a_bare_account_id(db):
    session, account = db
    session.add(
        AccountCookieVersion(
            platform_account_id=account.id, encrypted_cookies=encrypt_text(JSON_COOKIES)
        )
    )
    session.commit()
    assert latest_cookies(session, account.id).startswith("a1=")


# --- no module may decrypt a cookie version on its own ----------------------


def test_no_module_decrypts_cookie_versions_directly():
    """One storage shape, one accessor.

    A second implementation is how this bug appeared: six callers normalised,
    one did not, and the difference was invisible until a login changed the
    stored format.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "backend"
    allowed = {
        "backend/app/services/account_cookies.py",
    }
    offenders: list[str] = []
    pattern = re.compile(
        r"decrypt_text\(\s*\w*\.?encrypted_cookies\s*\)|decrypt_text\(cookie_version\.encrypted_cookies\)"
    )
    for path in root.rglob("*.py"):
        rel = path.relative_to(root.parent).as_posix()
        if rel in allowed or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            offenders.append(rel)

    assert not offenders, (
        "这些文件自己解密码 Cookie，绕过了 account_cookies 的统一转换：\n  "
        + "\n  ".join(offenders)
        + "\n请改用 backend.app.services.account_cookies.latest_cookies"
    )
