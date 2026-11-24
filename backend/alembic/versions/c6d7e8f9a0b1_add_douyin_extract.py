"""douyin extract pipeline

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-10-24 23:45:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "douyin_extract_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False, server_default="manifest"),
        sa.Column("source", sa.Text(), nullable=False, server_default=""),
        sa.Column("account_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("stage", sa.String(length=24), nullable=False, server_default="discover"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("no_speech", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetch_media", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("transcribe", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("keep_media", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("limit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_dir", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_douyin_extract_jobs_user_id", "douyin_extract_jobs", ["user_id"]
    )

    op.create_table(
        "douyin_works",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("douyin_extract_jobs.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("work_id", sa.String(length=64), nullable=False),
        sa.Column("work_type", sa.String(length=16), nullable=False, server_default="video"),
        sa.Column("url", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("caption", sa.Text(), nullable=False, server_default=""),
        sa.Column("author_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("author_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("published_at", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("media_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("audio_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("transcript_source", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("transcript_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(length=512), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("job_id", "work_id", name="uq_douyin_work_job_work"),
    )
    op.create_index("ix_douyin_works_job_id", "douyin_works", ["job_id"])
    op.create_index("ix_douyin_works_user_id", "douyin_works", ["user_id"])
    op.create_index(
        "ix_douyin_work_user_author", "douyin_works", ["user_id", "author_id", "work_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_douyin_work_user_author", table_name="douyin_works")
    op.drop_index("ix_douyin_works_user_id", table_name="douyin_works")
    op.drop_index("ix_douyin_works_job_id", table_name="douyin_works")
    op.drop_table("douyin_works")
    op.drop_index("ix_douyin_extract_jobs_user_id", table_name="douyin_extract_jobs")
    op.drop_table("douyin_extract_jobs")
