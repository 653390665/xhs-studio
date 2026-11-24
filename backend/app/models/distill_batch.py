from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class DistillBatch(Base):
    """A named box of distilled material (the four template kinds).

    Why this exists: batches used to live only in the browser
    (``localStorage["xhs.studio.results.<id>"]``). Clearing site data, switching
    browsers or opening the workbench on another machine silently lost every
    batch, and the writing page could only offer an empty picker.

    A batch is not a corpus set. A corpus set is *input* (which notes were
    studied); a batch is *output* (what the workbench wrote after reading them).
    One corpus can produce several batches over time, so the link is optional
    and never cascades.
    """

    __tablename__ = "distill_batches"
    __table_args__ = (
        Index("ix_distill_batches_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    # Where the material came from, when known. Nullable on purpose: batches
    # created in the workbench before this table existed have no source.
    source_set_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("corpus_sets.id"), nullable=True, index=True
    )
    # Free-form: the workbench knows more than this schema (notes count, brief).
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, onupdate=shanghai_now
    )


class DistillBatchItem(Base):
    """One of the four template kinds inside a batch: full / title / hook / image."""

    __tablename__ = "distill_batch_items"
    __table_args__ = (
        Index("uq_distill_batch_items_kind", "batch_id", "kind", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("distill_batches.id"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # full | title | hook | image
    kind: Mapped[str] = mapped_column(String(16), default="full")
    title: Mapped[str] = mapped_column(String(256), default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, onupdate=shanghai_now
    )
