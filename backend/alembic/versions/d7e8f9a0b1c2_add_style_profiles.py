"""style profiles distilled from extracted corpora

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-10-25 01:10:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "style_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "source_job_id",
            sa.Integer(),
            sa.ForeignKey("douyin_extract_jobs.id"),
            nullable=True,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("platform_accounts.id"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=128), nullable=False, server_default="风格蒸馏"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ready"),
        sa.Column("works_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("engine", sa.String(length=32), nullable=False, server_default="heuristic"),
        sa.Column("profile_json", sa.JSON(), nullable=True),
        sa.Column("skill_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_style_profiles_user_id", "style_profiles", ["user_id"])
    op.create_index("ix_style_profiles_source_job_id", "style_profiles", ["source_job_id"])
    op.create_index("ix_style_profiles_account_id", "style_profiles", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_style_profiles_account_id", table_name="style_profiles")
    op.drop_index("ix_style_profiles_source_job_id", table_name="style_profiles")
    op.drop_index("ix_style_profiles_user_id", table_name="style_profiles")
    op.drop_table("style_profiles")
