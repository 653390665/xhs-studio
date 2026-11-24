"""add unique note index

Revision ID: c0d1e2f3a4b5
Revises: a8b9c0d1e2f3
Create Date: 2026-10-24 11:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The application already upserts by (user_id, platform, note_id); the
    # unique index prevents duplicates under concurrent requests.
    op.create_index(
        "uq_notes_user_platform_note",
        "notes",
        ["user_id", "platform", "note_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_notes_user_platform_note", table_name="notes")
