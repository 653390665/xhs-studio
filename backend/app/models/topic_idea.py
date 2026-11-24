from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class TopicIdea(Base):
    """A saved topic from the seven-type topic bank."""

    __tablename__ = "topic_ideas"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "platform_account_id", "title", name="uq_topic_idea_user_account_title"
        ),
        Index("ix_topic_ideas_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("platform_accounts.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(24), default="pain")
    type_label: Mapped[str] = mapped_column(String(32), default="")
    growth_task: Mapped[str] = mapped_column(String(24), default="建立信任")
    need: Mapped[str] = mapped_column(String(64), default="")
    why: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(24), default="model")
    status: Mapped[str] = mapped_column(String(16), default="new")  # new/used/archived
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, onupdate=shanghai_now
    )
