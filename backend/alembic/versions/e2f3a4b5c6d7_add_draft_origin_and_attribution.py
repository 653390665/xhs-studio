"""add draft origin and publish attribution

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-24 18:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_drafts",
        sa.Column("origin", sa.String(length=32), nullable=False, server_default="manual"),
    )
    op.add_column(
        "ai_drafts",
        sa.Column("pipeline_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_drafts",
        sa.Column("skill_version", sa.String(length=32), nullable=False, server_default=""),
    )
    op.create_index("ix_ai_drafts_origin", "ai_drafts", ["origin"])
    op.create_index("ix_ai_drafts_pipeline_id", "ai_drafts", ["pipeline_id"])

    op.add_column(
        "publish_jobs",
        sa.Column("origin", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "publish_jobs",
        sa.Column("skill_version", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "publish_jobs",
        sa.Column("pillar", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "publish_jobs",
        sa.Column("experiment", sa.String(length=64), nullable=False, server_default=""),
    )
    op.create_index("ix_publish_jobs_origin", "publish_jobs", ["origin"])


def downgrade() -> None:
    op.drop_index("ix_publish_jobs_origin", table_name="publish_jobs")
    op.drop_column("publish_jobs", "experiment")
    op.drop_column("publish_jobs", "pillar")
    op.drop_column("publish_jobs", "skill_version")
    op.drop_column("publish_jobs", "origin")

    op.drop_index("ix_ai_drafts_pipeline_id", table_name="ai_drafts")
    op.drop_index("ix_ai_drafts_origin", table_name="ai_drafts")
    op.drop_column("ai_drafts", "skill_version")
    op.drop_column("ai_drafts", "pipeline_id")
    op.drop_column("ai_drafts", "origin")
