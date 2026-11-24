from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class RiskControlSetting(Base):
    """Explicit opt-in switches for high-risk automation.

    Every switch defaults to ``False``. Enabling a high-risk switch requires
    an explicit acknowledgement from the user; the product never turns these
    on silently.
    """

    __tablename__ = "risk_control_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)

    auto_ops_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    competitor_rewrite_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    copy_source_images_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_create_publish_job_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_publish_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Reserved: not implemented yet, but kept in the model so future features
    # cannot be enabled without the same explicit opt-in flow.
    auto_engagement_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    matrix_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    batch_repost_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)
