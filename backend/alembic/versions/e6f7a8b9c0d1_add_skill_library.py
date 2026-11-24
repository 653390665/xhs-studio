"""add skill library

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-10-23 22:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_library_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("module", sa.String(length=32), nullable=False, server_default="general"),
        sa.Column("triggers", sa.JSON(), nullable=True),
        sa.Column("content_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("license", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "slug", name="uq_skill_library_user_slug"),
    )
    op.create_index("ix_skill_library_items_user_id", "skill_library_items", ["user_id"])
    op.create_index("ix_skill_library_items_module", "skill_library_items", ["module"])
    op.create_index(
        "ix_skill_library_user_module",
        "skill_library_items",
        ["user_id", "module", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_skill_library_user_module", table_name="skill_library_items")
    op.drop_index("ix_skill_library_items_module", table_name="skill_library_items")
    op.drop_index("ix_skill_library_items_user_id", table_name="skill_library_items")
    op.drop_table("skill_library_items")
