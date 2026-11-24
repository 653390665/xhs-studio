"""add keyword hit snapshots

Revision ID: j3e4f5a6b7c8
Revises: i2d3e4f5a6b7
Create Date: 2026-10-26 05:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'j3e4f5a6b7c8'
down_revision: Union[str, None] = 'i2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'keyword_hit_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('keyword', sa.String(length=128), nullable=False),
        sa.Column('group_name', sa.String(length=128), nullable=False),
        sa.Column('snapshot_date', sa.String(length=10), nullable=False),
        sa.Column('notes', sa.Integer(), nullable=False),
        sa.Column('engagement', sa.Integer(), nullable=False),
        sa.Column('captured_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'keyword', 'snapshot_date', name='uq_keyword_hit_day'
        ),
    )
    op.create_index(
        'ix_keyword_hit_snapshots_user_id', 'keyword_hit_snapshots', ['user_id']
    )
    op.create_index(
        'ix_keyword_hit_snapshots_keyword', 'keyword_hit_snapshots', ['keyword']
    )
    op.create_index(
        'ix_keyword_hit_snapshots_snapshot_date',
        'keyword_hit_snapshots',
        ['snapshot_date'],
    )
    op.create_index(
        'ix_keyword_hit_user_date', 'keyword_hit_snapshots', ['user_id', 'snapshot_date']
    )


def downgrade() -> None:
    op.drop_index('ix_keyword_hit_user_date', table_name='keyword_hit_snapshots')
    op.drop_index('ix_keyword_hit_snapshots_snapshot_date', table_name='keyword_hit_snapshots')
    op.drop_index('ix_keyword_hit_snapshots_keyword', table_name='keyword_hit_snapshots')
    op.drop_index('ix_keyword_hit_snapshots_user_id', table_name='keyword_hit_snapshots')
    op.drop_table('keyword_hit_snapshots')
