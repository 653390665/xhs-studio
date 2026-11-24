"""Cookie storage is JSON; the SDK wants a ``k=v; k=v`` header.

Stored cookies are a JSON object (what QR/phone login captures). The XHS SDK
parses a cookie *header*, so passing the raw JSON makes ``XHSPcAuth`` fail with
"must contain a1" — the cookie is right there, just in the wrong shape.

Seven modules read ``AccountCookieVersion`` independently. Six normalise; one
did not, and the failure only appears with JSON-format cookies, so the broken
path looked fine as long as logins produced header strings.

This module is the single place that knows the shape. New callers must use it
rather than decrypting a cookie version themselves.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import decrypt_text
from backend.app.models import AccountCookieVersion, PlatformAccount

__all__ = ["cookies_to_string", "latest_cookies", "latest_cookie_version"]


def cookies_to_string(value: str) -> str:
    """Normalise a stored cookie blob into an HTTP ``Cookie`` header value.

    Accepts either the JSON object written by the login flows or an
    already-formatted header string, so historical rows keep working.
    """
    stripped = (value or "").strip()
    if not stripped:
        return stripped
    if stripped.startswith("{"):
        try:
            cookies = json.loads(stripped)
        except ValueError:
            return stripped
        if not isinstance(cookies, dict):
            return stripped
        return "; ".join(f"{key}={cookie_value}" for key, cookie_value in cookies.items())
    return stripped


def latest_cookie_version(db: Session, account_id: int) -> AccountCookieVersion | None:
    return db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account_id)
        .order_by(
            AccountCookieVersion.created_at.desc(), AccountCookieVersion.id.desc()
        )
    ).first()


def latest_cookies(
    db: Session,
    account: PlatformAccount | int,
    *,
    missing_detail: str = "该账号没有可用的 Cookie，请重新登录",
) -> str:
    """The account's newest cookies, ready to hand to an adapter."""
    account_id = account.id if isinstance(account, PlatformAccount) else account
    version = latest_cookie_version(db, account_id)
    if version is None:
        raise LookupError(missing_detail)
    return cookies_to_string(decrypt_text(version.encrypted_cookies))
