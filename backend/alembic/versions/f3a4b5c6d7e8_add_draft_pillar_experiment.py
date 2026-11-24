"""add draft pillar and experiment

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-10-24 22:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_drafts",
        sa.Column("pillar", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "ai_drafts",
        sa.Column("experiment", sa.String(length=64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("ai_drafts", "experiment")
    op.drop_column("ai_drafts", "pillar")
