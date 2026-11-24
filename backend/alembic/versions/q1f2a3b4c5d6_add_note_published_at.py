"""add notes.published_at

Why: ``created_at`` records when we crawled a note, not when the author posted
it. "低粉爆款" (low-follower breakout) needs the publication date — a
low-follower hit from 2021 says nothing about what works now. Every recency
filter was therefore impossible without confusing the two facts.

Nullable on purpose: existing rows and adapters that return no timestamp stay
NULL, meaning "unknown" rather than "today".

Revision ID: q1f2a3b4c5d6
Revises: p9e0f1a2b3c4
Create Date: 2026-11-11 20:10:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q1f2a3b4c5d6"
down_revision: Union[str, None] = "p9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if _has_column("notes", "published_at"):
        return
    op.add_column("notes", sa.Column("published_at", sa.DateTime(), nullable=True))
    op.create_index("ix_notes_published_at", "notes", ["published_at"], unique=False)


def downgrade() -> None:
    if not _has_column("notes", "published_at"):
        return
    op.drop_index("ix_notes_published_at", table_name="notes")
    op.drop_column("notes", "published_at")
