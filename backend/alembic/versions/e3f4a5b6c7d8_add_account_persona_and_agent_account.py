"""add account persona, agent memory and account binding

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-10-23 02:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_drafts", sa.Column("platform_account_id", sa.Integer(), nullable=True))
    op.create_index("ix_ai_drafts_platform_account_id", "ai_drafts", ["platform_account_id"])

    op.add_column("agent_runs", sa.Column("platform_account_id", sa.Integer(), nullable=True))
    op.create_index("ix_agent_runs_platform_account_id", "agent_runs", ["platform_account_id"])

    op.create_table(
        "account_personas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform_account_id", sa.Integer(), nullable=False),
        sa.Column("positioning", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("tone", sa.Text(), nullable=False),
        sa.Column("pillars", sa.JSON(), nullable=True),
        sa.Column("taboos", sa.JSON(), nullable=True),
        sa.Column("products", sa.Text(), nullable=False),
        sa.Column("cta_style", sa.Text(), nullable=False),
        sa.Column("visual_style", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["platform_account_id"], ["platform_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_account_personas_user_id", "account_personas", ["user_id"])
    op.create_index(
        "ix_account_personas_platform_account_id",
        "account_personas",
        ["platform_account_id"],
        unique=True,
    )

    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform_account_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["platform_account_id"], ["platform_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_memories_user_id", "agent_memories", ["user_id"])
    op.create_index("ix_agent_memories_platform_account_id", "agent_memories", ["platform_account_id"])
    op.create_index("ix_agent_memories_kind", "agent_memories", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_agent_memories_kind", table_name="agent_memories")
    op.drop_index("ix_agent_memories_platform_account_id", table_name="agent_memories")
    op.drop_index("ix_agent_memories_user_id", table_name="agent_memories")
    op.drop_table("agent_memories")

    op.drop_index("ix_account_personas_platform_account_id", table_name="account_personas")
    op.drop_index("ix_account_personas_user_id", table_name="account_personas")
    op.drop_table("account_personas")

    op.drop_index("ix_agent_runs_platform_account_id", table_name="agent_runs")
    op.drop_column("agent_runs", "platform_account_id")
    op.drop_index("ix_ai_drafts_platform_account_id", table_name="ai_drafts")
    op.drop_column("ai_drafts", "platform_account_id")
