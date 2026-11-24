"""index auto task template reference

Revision ID: p9e0f1a2b3c4
Revises: o8d9e0f1a2b3
Create Date: 2026-10-30 04:10:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "p9e0f1a2b3c4"
down_revision: Union[str, None] = "o8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_auto_tasks_template_id",
        "auto_tasks",
        ["template_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auto_tasks_template_id", table_name="auto_tasks")
