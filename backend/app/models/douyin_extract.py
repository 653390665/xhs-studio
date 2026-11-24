from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class DouyinExtractJob(Base):
    """One content-extraction run for a Douyin account or a work list.

    The pipeline mirrors the imported ``douyin-content-extraction`` Skill:
    discover → download → transcribe → review → deliver. Every stage is
    resumable and only counts work that actually produced output.
    """

    __tablename__ = "douyin_extract_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16), default="manifest")
    source: Mapped[str] = mapped_column(Text, default="")
    account_name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(24), default="draft")
    stage: Mapped[str] = mapped_column(String(24), default="discover")
    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    no_speech: Mapped[int] = mapped_column(Integer, default=0)
    fetch_media: Mapped[bool] = mapped_column(Boolean, default=True)
    transcribe: Mapped[bool] = mapped_column(Boolean, default=True)
    keep_media: Mapped[bool] = mapped_column(Boolean, default=False)
    limit_count: Mapped[int] = mapped_column(Integer, default=0)
    output_dir: Mapped[str] = mapped_column(String(512), default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    options: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, onupdate=shanghai_now
    )


class DouyinWork(Base):
    """One discovered Douyin work and its extraction state."""

    __tablename__ = "douyin_works"
    __table_args__ = (
        UniqueConstraint("job_id", "work_id", name="uq_douyin_work_job_work"),
        Index("ix_douyin_work_user_author", "user_id", "author_id", "work_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("douyin_extract_jobs.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    work_id: Mapped[str] = mapped_column(String(64))
    work_type: Mapped[str] = mapped_column(String(16), default="video")
    url: Mapped[str] = mapped_column(String(1024), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    author_name: Mapped[str] = mapped_column(String(128), default="")
    author_id: Mapped[str] = mapped_column(String(128), default="")
    published_at: Mapped[str] = mapped_column(String(32), default="")
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    media_path: Mapped[str] = mapped_column(String(512), default="")
    audio_path: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    transcript_source: Mapped[str] = mapped_column(String(16), default="")
    transcript_chars: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, onupdate=shanghai_now
    )
