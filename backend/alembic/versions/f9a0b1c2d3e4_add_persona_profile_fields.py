"""persona extended profile fields

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-10-25 10:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("account_personas", sa.Column("language_samples", sa.JSON(), nullable=True))
    op.add_column("account_personas", sa.Column("trust_assets", sa.JSON(), nullable=True))
    op.add_column(
        "account_personas",
        sa.Column("persona_rules", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("account_personas", sa.Column("content_pipeline", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("account_personas", "content_pipeline")
    op.drop_column("account_personas", "persona_rules")
    op.drop_column("account_personas", "trust_assets")
    op.drop_column("account_personas", "language_samples")
