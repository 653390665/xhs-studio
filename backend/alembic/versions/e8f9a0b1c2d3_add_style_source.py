"""style profile source + builtin key

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-10-25 02:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "style_profiles",
        sa.Column("source", sa.String(length=24), nullable=False, server_default="distill"),
    )
    op.add_column(
        "style_profiles",
        sa.Column("builtin_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_style_profile_user_builtin",
        "style_profiles",
        ["user_id", "builtin_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_style_profile_user_builtin", table_name="style_profiles")
    op.drop_column("style_profiles", "builtin_key")
    op.drop_column("style_profiles", "source")
