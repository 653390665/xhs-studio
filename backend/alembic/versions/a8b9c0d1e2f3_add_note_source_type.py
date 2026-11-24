"""add note source type

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-10-24 10:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notes",
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="discovery"),
    )
    op.create_index("ix_notes_source_type", "notes", ["source_type"])

    # Best-effort backfill for existing rows. New writes set the column
    # explicitly; this only fixes historical data.
    op.execute(
        "UPDATE notes SET source_type='publish' "
        "WHERE raw_json LIKE '%\"origin\": \"publish\"%' "
        "OR raw_json LIKE '%\"origin\":\"publish\"%'"
    )
    op.execute(
        "UPDATE notes SET source_type='creator' "
        "WHERE raw_json LIKE '%\"source\": \"creator_published\"%' "
        "OR raw_json LIKE '%\"source\":\"creator_published\"%'"
    )


def downgrade() -> None:
    op.drop_index("ix_notes_source_type", table_name="notes")
    op.drop_column("notes", "source_type")
