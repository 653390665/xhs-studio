from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class SkillLibraryItem(Base):
    """Imported workflow Skill mapped to one product module.

    Unlike :class:`CreationSkill` (one active, account-specific playbook), a
    library item is a reusable task skill (topic bank, benchmark analysis,
    cover direction...). Several items can be enabled for the same module and
    their text is injected into that module's prompts on demand.
    """

    __tablename__ = "skill_library_items"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_skill_library_user_slug"),
        Index("ix_skill_library_user_module", "user_id", "module", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    slug: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    module: Mapped[str] = mapped_column(String(32), default="general", index=True)
    triggers: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    content_md: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(128), default="")
    license: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)


class AccountSkillSetting(Base):
    """Per-account enable/priority override for an imported library Skill."""

    __tablename__ = "account_skill_settings"
    __table_args__ = (
        UniqueConstraint("platform_account_id", "skill_item_id", name="uq_account_skill_item"),
        Index("ix_account_skill_user_account", "user_id", "platform_account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform_account_id: Mapped[int] = mapped_column(
        ForeignKey("platform_accounts.id"), index=True
    )
    skill_item_id: Mapped[int] = mapped_column(
        ForeignKey("skill_library_items.id"), index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)
