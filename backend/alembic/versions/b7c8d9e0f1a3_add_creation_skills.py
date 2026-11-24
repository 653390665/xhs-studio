"""add creation skills

Revision ID: b7c8d9e0f1a3
Revises: 9c1d2e3f4a5b
Create Date: 2026-10-23 17:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a3"
down_revision: Union[str, None] = "9c1d2e3f4a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "creation_skills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default="xhs"),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("structured_json", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["platform_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_creation_skills_user_id", "creation_skills", ["user_id"])
    op.create_index("ix_creation_skills_account_id", "creation_skills", ["account_id"])
    op.create_index(
        "ix_creation_skills_account_status",
        "creation_skills",
        ["user_id", "account_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_creation_skills_account_status", table_name="creation_skills")
    op.drop_index("ix_creation_skills_account_id", table_name="creation_skills")
    op.drop_index("ix_creation_skills_user_id", table_name="creation_skills")
    op.drop_table("creation_skills")
