"""add account positioning

Revision ID: k4f5a6b7c8d9
Revises: j3e4f5a6b7c8
Create Date: 2026-10-27 09:00:00.000000

Early-stage accounts have a positioning but no style. Storing positioning in
``style_profiles`` forced every account into a "style" concept it did not have,
and applying one style silently demoted the rest, so positioning and style
could never coexist. This table holds positioning only.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'k4f5a6b7c8d9'
down_revision: Union[str, None] = 'j3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'account_positioning',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('platform_account_id', sa.Integer(), nullable=False),
        sa.Column('positioning', sa.Text(), nullable=False, server_default=''),
        sa.Column('audience', sa.Text(), nullable=False, server_default=''),
        sa.Column('promise', sa.Text(), nullable=False, server_default=''),
        sa.Column('main_topics', sa.JSON(), nullable=True),
        sa.Column('taboos', sa.JSON(), nullable=True),
        sa.Column('language_samples', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(length=128), nullable=False, server_default='manual'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['platform_account_id'], ['platform_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_account_positioning_user_id', 'account_positioning', ['user_id']
    )
    op.create_index(
        'ix_account_positioning_platform_account_id',
        'account_positioning',
        ['platform_account_id'],
    )
    op.create_index(
        'uq_account_positioning_account',
        'account_positioning',
        ['platform_account_id'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_account_positioning_account', table_name='account_positioning')
    op.drop_index(
        'ix_account_positioning_platform_account_id', table_name='account_positioning'
    )
    op.drop_index('ix_account_positioning_user_id', table_name='account_positioning')
    op.drop_table('account_positioning')
