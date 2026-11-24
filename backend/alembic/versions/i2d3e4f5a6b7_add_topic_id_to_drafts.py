"""add topic_id to ai drafts

Revision ID: i2d3e4f5a6b7
Revises: h1c2d3e4f5a6
Create Date: 2026-10-25 18:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'i2d3e4f5a6b7'
down_revision: Union[str, None] = 'h1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ai_drafts', sa.Column('topic_id', sa.Integer(), nullable=True))
    op.create_index('ix_ai_drafts_topic_id', 'ai_drafts', ['topic_id'])


def downgrade() -> None:
    op.drop_index('ix_ai_drafts_topic_id', table_name='ai_drafts')
    op.drop_column('ai_drafts', 'topic_id')
