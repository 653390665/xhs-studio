"""add template activation and auto-task template

Revision ID: o8d9e0f1a2b3
Revises: n7c8d9e0f1a2
Create Date: 2026-10-30 03:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o8d9e0f1a2b3"
down_revision: Union[str, None] = "n7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "viral_templates",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "auto_tasks",
        sa.Column("template_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auto_tasks", "template_id")
    op.drop_column("viral_templates", "is_active")
