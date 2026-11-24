from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class MetricSnapshot(Base):
    """One metric value captured at a point in time.

    The EAV shape keeps new metrics additive: adding ``views`` or
    ``follows_gained`` does not require a schema change, and repeated captures
    for the same entity form a time series.
    """

    __tablename__ = "metric_snapshots"
    __table_args__ = (
        Index(
            "ix_metric_snapshots_lookup",
            "user_id",
            "scope",
            "ref_id",
            "metric_name",
            "captured_at",
        ),
        Index(
            "ix_metric_snapshots_platform_metric",
            "user_id",
            "platform",
            "metric_name",
            "captured_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)  # note / account
    ref_id: Mapped[int] = mapped_column(Integer, index=True)  # note.id or platform_accounts.id
    metric_name: Mapped[str] = mapped_column(String(64), index=True)
    metric_value: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, index=True)


class FeatureSnapshot(Base):
    """Structured content/account features produced by rules or AI.

    ``feature_json`` is intentionally flexible: title patterns, CTA, hooks,
    structure, cover analysis, comment sentiment, etc. all live here instead of
    being hard-coded into the scoring tables.
    """

    __tablename__ = "feature_snapshots"
    __table_args__ = (
        UniqueConstraint("scope", "ref_id", "feature_set", name="uq_feature_snapshot_entity_set"),
        Index("ix_feature_snapshots_lookup", "user_id", "scope", "ref_id", "feature_set"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)  # note / account
    ref_id: Mapped[int] = mapped_column(Integer, index=True)
    feature_set: Mapped[str] = mapped_column(String(64), default="content_rules_v1")
    feature_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="rules")
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class AnalysisRun(Base):
    """Lightweight audit row for backfills and diagnosis snapshots."""

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)  # backfill / account / note
    status: Mapped[str] = mapped_column(String(16), default="ok")
    params_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
