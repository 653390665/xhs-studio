"""Capture tokens: the browser extension's credential.

A capture token is deliberately separate from the login JWT:

* it can live for months without keeping a stale access token around;
* revoking it does not log the user out of the app;
* only the SHA-256 hash is stored, so a database read cannot recover it.
"""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import shanghai_now
from backend.app.models import CaptureToken, User

TOKEN_PREFIX = "xhs_cap_"


def hash_token(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def create_token(db: Session, user: User, *, name: str = "") -> tuple[CaptureToken, str]:
    """Create a token and return it once. The raw value is never stored."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = CaptureToken(
        user_id=user.id,
        name=(name or "")[:64],
        token_hash=hash_token(raw),
        token_prefix=raw[:14],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, raw


def list_tokens(db: Session, user: User) -> list[CaptureToken]:
    return list(
        db.scalars(
            select(CaptureToken)
            .where(CaptureToken.user_id == user.id)
            .order_by(CaptureToken.created_at.desc())
        ).all()
    )


def revoke_token(db: Session, user: User, token_id: int) -> bool:
    row = db.get(CaptureToken, token_id)
    if row is None or row.user_id != user.id or row.revoked_at is not None:
        return False
    row.revoked_at = shanghai_now()
    db.commit()
    return True


def resolve_user(db: Session, raw: str) -> User | None:
    """Return the token's owner, or None. Updates last_used_at on success."""
    if not raw:
        return None
    row = db.scalar(
        select(CaptureToken).where(
            CaptureToken.token_hash == hash_token(raw),
            CaptureToken.revoked_at.is_(None),
        )
    )
    if row is None:
        return None
    row.last_used_at = shanghai_now()
    db.commit()
    user = db.get(User, row.user_id)
    return user


__all__ = ["TOKEN_PREFIX", "create_token", "hash_token", "list_tokens", "resolve_user", "revoke_token"]
