"""add hot topic snapshots

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-10-22 05:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'hot_topic_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('snapshot_date', sa.String(length=10), nullable=False),
        sa.Column('hot_score', sa.Integer(), nullable=False),
        sa.Column('hot_text', sa.String(length=32), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('captured_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_date', 'title', name='uq_hot_topic_snapshot_day'),
    )
    op.create_index('ix_hot_topic_snapshots_title', 'hot_topic_snapshots', ['title'])
    op.create_index('ix_hot_topic_snapshots_snapshot_date', 'hot_topic_snapshots', ['snapshot_date'])


def downgrade() -> None:
    op.drop_index('ix_hot_topic_snapshots_snapshot_date', table_name='hot_topic_snapshots')
    op.drop_index('ix_hot_topic_snapshots_title', table_name='hot_topic_snapshots')
    op.drop_table('hot_topic_snapshots')
