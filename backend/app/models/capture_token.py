from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class CaptureToken(Base):
    """A long-lived credential for the browser extension.

    The browser extension runs on douyin.com and posts captured work lists to the
    local backend. Reusing the login JWT would mean re-pasting a short-lived token
    every day; a dedicated token can be revoked on its own without logging the
    user out. Only the SHA-256 hash is stored.
    """

    __tablename__ = "capture_tokens"
    __table_args__ = (Index("ix_capture_tokens_hash", "token_hash", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    token_hash: Mapped[str] = mapped_column(String(64))
    # First characters, shown in the UI so a token can be recognised without
    # revealing it again.
    token_prefix: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
