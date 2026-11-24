"""add draft review status

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-10-24 16:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_drafts",
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="pending"),
    )
    op.create_index("ix_ai_drafts_review_status", "ai_drafts", ["review_status"])


def downgrade() -> None:
    op.drop_index("ix_ai_drafts_review_status", table_name="ai_drafts")
    op.drop_column("ai_drafts", "review_status")
