"""add draft chat messages and draft versions

Revision ID: d5e6f7a8b9c0
Revises: b7c8d9e0f1a3
Create Date: 2026-10-23 18:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "b7c8d9e0f1a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "draft_chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("patch_json", sa.JSON(), nullable=True),
        sa.Column("score_json", sa.JSON(), nullable=True),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("skill_version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["draft_id"], ["ai_drafts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_draft_chat_messages_user_id", "draft_chat_messages", ["user_id"])
    op.create_index("ix_draft_chat_messages_draft_id", "draft_chat_messages", ["draft_id"])
    op.create_index(
        "ix_draft_chat_draft_created",
        "draft_chat_messages",
        ["draft_id", "created_at"],
    )

    op.create_table(
        "draft_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="chat"),
        sa.Column("chat_message_id", sa.Integer(), nullable=True),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("skill_version", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["draft_id"], ["ai_drafts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_draft_versions_user_id", "draft_versions", ["user_id"])
    op.create_index("ix_draft_versions_draft_id", "draft_versions", ["draft_id"])
    op.create_index("ix_draft_versions_draft", "draft_versions", ["draft_id", "version_no"])


def downgrade() -> None:
    op.drop_index("ix_draft_versions_draft", table_name="draft_versions")
    op.drop_index("ix_draft_versions_draft_id", table_name="draft_versions")
    op.drop_index("ix_draft_versions_user_id", table_name="draft_versions")
    op.drop_table("draft_versions")

    op.drop_index("ix_draft_chat_draft_created", table_name="draft_chat_messages")
    op.drop_index("ix_draft_chat_messages_draft_id", table_name="draft_chat_messages")
    op.drop_index("ix_draft_chat_messages_user_id", table_name="draft_chat_messages")
    op.drop_table("draft_chat_messages")
