"""add viral analysis and template tables

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-10-20 15:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'viral_analyses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('note_db_id', sa.Integer(), nullable=True),
        sa.Column('note_id', sa.String(length=128), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['note_db_id'], ['notes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_viral_analyses_user_id', 'viral_analyses', ['user_id'])
    op.create_index('ix_viral_analyses_note_db_id', 'viral_analyses', ['note_db_id'])
    op.create_index('ix_viral_analyses_note_id', 'viral_analyses', ['note_id'])

    op.create_table(
        'viral_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('source_note_ids', sa.JSON(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_viral_templates_user_id', 'viral_templates', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_viral_templates_user_id', table_name='viral_templates')
    op.drop_table('viral_templates')
    op.drop_index('ix_viral_analyses_note_id', table_name='viral_analyses')
    op.drop_index('ix_viral_analyses_note_db_id', table_name='viral_analyses')
    op.drop_index('ix_viral_analyses_user_id', table_name='viral_analyses')
    op.drop_table('viral_analyses')
