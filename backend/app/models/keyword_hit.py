"""Keyword hit snapshots: daily counts so “热词追踪” has a real trend.

The existing `hot_topic_snapshots` table tracks platform hot searches. This one
tracks the user's own keyword groups against the sample library, which is what
the keywords page actually needs in order to show rise / fall.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class KeywordHitSnapshot(Base):
    """One row per (user, keyword, day)."""

    __tablename__ = "keyword_hit_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "keyword", "snapshot_date", name="uq_keyword_hit_day"
        ),
        Index("ix_keyword_hit_user_date", "user_id", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    snapshot_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    notes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engagement: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, nullable=False
    )
