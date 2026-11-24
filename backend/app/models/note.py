from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Table, Text, Column
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


note_tags = Table(
    "note_tags",
    Base.metadata,
    Column("note_id", ForeignKey("notes.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("uq_notes_user_platform_note", "user_id", "platform", "note_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, default=0)
    platform_account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    note_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    author_name: Mapped[str] = mapped_column(String(128), default="")
    author_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    author_fans: Mapped[int] = mapped_column(Integer, default=0)
    # ``author_fans=0`` used to mean two different things: "the author really has
    # no followers" and "we never fetched a profile". 97 of 104 crawled notes
    # carried the second meaning while showing the first, so every low-follower
    # filter silently dropped them (75 of them had 1,000+ likes).
    #
    # unknown — never fetched; not evidence of anything
    # known   — fetched from the platform, including a genuine 0
    author_fans_status: Mapped[str] = mapped_column(
        String(16), default="unknown", index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), default="discovery", index=True)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    collect_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    like_fan_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    metrics_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # When the author posted it, as a real datetime.
    #
    # ``created_at`` is when *we* crawled it, which is a different fact: a note
    # crawled today may have been published three years ago. "低粉爆款" needs the
    # publication date because a low-follower post that blew up is only
    # interesting if it is recent — a 2021 hit says nothing about what works now.
    #
    # Nullable on purpose: older rows and any adapter that does not return a
    # timestamp stay NULL, which means "unknown", not "today". Filtering by
    # recency excludes them rather than pretending.
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class NoteAsset(Base):
    __tablename__ = "note_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text)
    local_path: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class NoteComment(Base):
    __tablename__ = "note_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), index=True)
    comment_id: Mapped[str] = mapped_column(String(128), index=True)
    user_name: Mapped[str] = mapped_column(String(128), default="")
    user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    parent_comment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at_remote: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    color: Mapped[str] = mapped_column(String(24), default="#111111")
