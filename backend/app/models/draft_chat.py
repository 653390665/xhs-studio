from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class DraftChatMessage(Base):
    """Persisted conversation for one draft."""

    __tablename__ = "draft_chat_messages"
    __table_args__ = (Index("ix_draft_chat_draft_created", "draft_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("ai_drafts.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text, default="")
    patch_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    score_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    skill_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    skill_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class DraftVersion(Base):
    """Immutable snapshot created when a chat suggestion is applied."""

    __tablename__ = "draft_versions"
    __table_args__ = (Index("ix_draft_versions_draft", "draft_id", "version_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("ai_drafts.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(256), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="chat")
    chat_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    skill_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    skill_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
