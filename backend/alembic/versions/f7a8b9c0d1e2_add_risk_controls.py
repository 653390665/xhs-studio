"""add risk control settings

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-10-24 09:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_control_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("auto_ops_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("competitor_rewrite_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("copy_source_images_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_create_publish_job_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_publish_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_engagement_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("matrix_mode_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("batch_repost_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_risk_control_settings_user_id", "risk_control_settings", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_risk_control_settings_user_id", table_name="risk_control_settings")
    op.drop_table("risk_control_settings")
