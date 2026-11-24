"""add author fans status

Revision ID: m6b7c8d9e0f1
Revises: l5a6b7c8d9e0
Create Date: 2026-10-27 12:00:00.000000

``author_fans = 0`` meant both "the author genuinely has no followers" and "we
never fetched a profile". 97 of 104 crawled notes carried the second meaning, and
every low-follower filter dropped them — 75 of those had 1,000+ likes.

This adds an explicit status so the distinction survives:

* backfill existing rows: ``known`` when ``author_fans > 0``, else ``unknown``
* new rows default to ``unknown`` until a profile fetch succeeds
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'm6b7c8d9e0f1'
down_revision: Union[str, None] = 'l5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'notes',
        sa.Column(
            'author_fans_status',
            sa.String(length=16),
            nullable=False,
            server_default='unknown',
        ),
    )
    op.create_index(
        'ix_notes_author_fans_status', 'notes', ['author_fans_status']
    )
    # Anything with a positive count was definitely fetched. Everything else is
    # unknown: we cannot tell a real zero from a missing fetch after the fact, so
    # guessing would recreate the defect.
    op.execute(
        "UPDATE notes SET author_fans_status = 'known' WHERE author_fans > 0"
    )


def downgrade() -> None:
    op.drop_index('ix_notes_author_fans_status', table_name='notes')
    op.drop_column('notes', 'author_fans_status')
