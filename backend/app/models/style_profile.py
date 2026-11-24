from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class StyleProfile(Base):
    """A writing-style distillation produced from an extracted corpus.

    ``profile_json`` holds the measurable statistics plus the (optional) model
    analysis; ``skill_md`` is the human-readable playbook that can be applied
    to an account as a draft CreationSkill.
    """

    __tablename__ = "style_profiles"
    __table_args__ = (
        Index("uq_style_profile_user_builtin", "user_id", "builtin_key", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("douyin_extract_jobs.id"), nullable=True, index=True
    )
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("platform_accounts.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(128), default="风格蒸馏")
    status: Mapped[str] = mapped_column(String(16), default="ready")  # ready/applied
    source: Mapped[str] = mapped_column(String(24), default="distill")  # distill/builtin
    builtin_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    works_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    engine: Mapped[str] = mapped_column(String(32), default="heuristic")
    profile_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    skill_md: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, onupdate=shanghai_now
    )
