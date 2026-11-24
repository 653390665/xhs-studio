"""add template_id to ai drafts

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-10-22 16:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ai_drafts', sa.Column('template_id', sa.Integer(), nullable=True))
    op.create_index('ix_ai_drafts_template_id', 'ai_drafts', ['template_id'])


def downgrade() -> None:
    op.drop_index('ix_ai_drafts_template_id', table_name='ai_drafts')
    op.drop_column('ai_drafts', 'template_id')
