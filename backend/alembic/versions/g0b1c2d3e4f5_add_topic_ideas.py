"""topic ideas pool

Revision ID: g0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-10-25 11:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g0b1c2d3e4f5"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "topic_ideas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "platform_account_id",
            sa.Integer(),
            sa.ForeignKey("platform_accounts.id"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=24), nullable=False, server_default="pain"),
        sa.Column("type_label", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("growth_task", sa.String(length=24), nullable=False, server_default="建立信任"),
        sa.Column("need", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("why", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=24), nullable=False, server_default="model"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "platform_account_id", "title", name="uq_topic_idea_user_account_title"
        ),
    )
    op.create_index("ix_topic_ideas_user_id", "topic_ideas", ["user_id"])
    op.create_index("ix_topic_ideas_platform_account_id", "topic_ideas", ["platform_account_id"])
    op.create_index("ix_topic_ideas_user_status", "topic_ideas", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_topic_ideas_user_status", table_name="topic_ideas")
    op.drop_index("ix_topic_ideas_platform_account_id", table_name="topic_ideas")
    op.drop_index("ix_topic_ideas_user_id", table_name="topic_ideas")
    op.drop_table("topic_ideas")
