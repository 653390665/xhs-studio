"""add topic schedule date

Revision ID: h1c2d3e4f5a6
Revises: g0b1c2d3e4f5
Create Date: 2026-10-25 16:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h1c2d3e4f5a6"
down_revision: Union[str, None] = "g0b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "topic_ideas",
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_topic_ideas_scheduled_for",
        "topic_ideas",
        ["scheduled_for"],
    )


def downgrade() -> None:
    op.drop_index("ix_topic_ideas_scheduled_for", table_name="topic_ideas")
    op.drop_column("topic_ideas", "scheduled_for")
