from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


DEFAULT_TEXT_MODEL_NAME = "gpt-5.4"


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    model_type: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128), default="")
    base_url: Mapped[str] = mapped_column(Text, default="")
    encrypted_api_key: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class AiDraft(Base):
    __tablename__ = "ai_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    platform_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("platform_accounts.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(256), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source_note_id: Mapped[Optional[int]] = mapped_column(ForeignKey("notes.id"), nullable=True)
    template_id: Mapped[Optional[int]] = mapped_column(ForeignKey("viral_templates.id"), nullable=True, index=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topic_ideas.id"), nullable=True, index=True)
    origin: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    pipeline_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    skill_version: Mapped[str] = mapped_column(String(32), default="")
    pillar: Mapped[str] = mapped_column(String(64), default="")
    experiment: Mapped[str] = mapped_column(String(64), default="")
    review_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # Which batch produced this draft, and what the prompt actually contained.
    #
    # ``skill_version`` alone ("style-16") cannot answer "why does this draft
    # read like this" three weeks later, and it cannot be backfilled. Storing the
    # whole context at generation time costs one JSON column and makes every
    # later question (which style? which template? which skills? which batch?)
    # answerable instead of archaeological.
    batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("distill_batches.id"), nullable=True, index=True
    )
    context_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class AiGeneratedAsset(Base):
    __tablename__ = "ai_generated_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    draft_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_drafts.id"), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(128), default="")
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    file_path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class DraftAsset(Base):
    __tablename__ = "draft_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("ai_drafts.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text, default="")
    local_path: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
