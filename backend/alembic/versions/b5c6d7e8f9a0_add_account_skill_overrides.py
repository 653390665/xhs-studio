"""add account skill overrides

Revision ID: b5c6d7e8f9a0
Revises: f3a4b5c6d7e8
Create Date: 2026-10-24 23:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_skill_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "platform_account_id",
            sa.Integer(),
            sa.ForeignKey("platform_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "skill_item_id",
            sa.Integer(),
            sa.ForeignKey("skill_library_items.id"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "platform_account_id", "skill_item_id", name="uq_account_skill_item"
        ),
    )
    op.create_index(
        "ix_account_skill_user_account",
        "account_skill_settings",
        ["user_id", "platform_account_id"],
    )
    op.create_index(
        "ix_account_skill_settings_user_id",
        "account_skill_settings",
        ["user_id"],
    )
    op.create_index(
        "ix_account_skill_settings_platform_account_id",
        "account_skill_settings",
        ["platform_account_id"],
    )
    op.create_index(
        "ix_account_skill_settings_skill_item_id",
        "account_skill_settings",
        ["skill_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_skill_settings_skill_item_id", table_name="account_skill_settings")
    op.drop_index("ix_account_skill_settings_platform_account_id", table_name="account_skill_settings")
    op.drop_index("ix_account_skill_settings_user_id", table_name="account_skill_settings")
    op.drop_index("ix_account_skill_user_account", table_name="account_skill_settings")
    op.drop_table("account_skill_settings")
