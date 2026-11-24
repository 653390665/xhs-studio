"""add capture tokens

Revision ID: n7c8d9e0f1a2
Revises: m6b7c8d9e0f1
Create Date: 2026-10-29 21:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n7c8d9e0f1a2"
down_revision: Union[str, None] = "m6b7c8d9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "capture_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_capture_tokens_user_id", "capture_tokens", ["user_id"])
    op.create_index(
        "ix_capture_tokens_hash", "capture_tokens", ["token_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_capture_tokens_hash", table_name="capture_tokens")
    op.drop_index("ix_capture_tokens_user_id", table_name="capture_tokens")
    op.drop_table("capture_tokens")
