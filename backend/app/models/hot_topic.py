"""Hot-topic snapshot model: daily time series for hot-search topics."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class HotTopicSnapshot(Base):
    """One row per (topic, day).

    Captured whenever the hot list is fetched, so we can tell whether a topic is
    rising or falling. Only aggregated hot-search data is stored (no user data).
    """

    __tablename__ = "hot_topic_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "title", name="uq_hot_topic_snapshot_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    hot_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hot_text: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    rank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
