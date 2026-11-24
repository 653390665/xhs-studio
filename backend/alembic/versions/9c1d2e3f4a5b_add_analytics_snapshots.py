"""add metric snapshots, feature snapshots and analysis runs

Revision ID: 9c1d2e3f4a5b
Revises: e3f4a5b6c7d8
Create Date: 2026-10-23 14:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9c1d2e3f4a5b"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metric_snapshots_user_id", "metric_snapshots", ["user_id"])
    op.create_index("ix_metric_snapshots_platform", "metric_snapshots", ["platform"])
    op.create_index("ix_metric_snapshots_scope", "metric_snapshots", ["scope"])
    op.create_index("ix_metric_snapshots_ref_id", "metric_snapshots", ["ref_id"])
    op.create_index("ix_metric_snapshots_metric_name", "metric_snapshots", ["metric_name"])
    op.create_index("ix_metric_snapshots_captured_at", "metric_snapshots", ["captured_at"])
    op.create_index(
        "ix_metric_snapshots_lookup",
        "metric_snapshots",
        ["user_id", "scope", "ref_id", "metric_name", "captured_at"],
    )
    op.create_index(
        "ix_metric_snapshots_platform_metric",
        "metric_snapshots",
        ["user_id", "platform", "metric_name", "captured_at"],
    )

    op.create_table(
        "feature_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("feature_set", sa.String(length=64), nullable=False, server_default="content_rules_v1"),
        sa.Column("feature_json", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="rules"),
        sa.Column("analyzed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "ref_id", "feature_set", name="uq_feature_snapshot_entity_set"),
    )
    op.create_index("ix_feature_snapshots_user_id", "feature_snapshots", ["user_id"])
    op.create_index("ix_feature_snapshots_platform", "feature_snapshots", ["platform"])
    op.create_index("ix_feature_snapshots_scope", "feature_snapshots", ["scope"])
    op.create_index("ix_feature_snapshots_ref_id", "feature_snapshots", ["ref_id"])
    op.create_index(
        "ix_feature_snapshots_lookup",
        "feature_snapshots",
        ["user_id", "scope", "ref_id", "feature_set"],
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ok"),
        sa.Column("params_json", sa.JSON(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_runs_user_id", "analysis_runs", ["user_id"])
    op.create_index("ix_analysis_runs_scope", "analysis_runs", ["scope"])


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_scope", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_user_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")

    op.drop_index("ix_feature_snapshots_lookup", table_name="feature_snapshots")
    op.drop_index("ix_feature_snapshots_ref_id", table_name="feature_snapshots")
    op.drop_index("ix_feature_snapshots_scope", table_name="feature_snapshots")
    op.drop_index("ix_feature_snapshots_platform", table_name="feature_snapshots")
    op.drop_index("ix_feature_snapshots_user_id", table_name="feature_snapshots")
    op.drop_table("feature_snapshots")

    op.drop_index("ix_metric_snapshots_platform_metric", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_lookup", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_captured_at", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_metric_name", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_ref_id", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_scope", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_platform", table_name="metric_snapshots")
    op.drop_index("ix_metric_snapshots_user_id", table_name="metric_snapshots")
    op.drop_table("metric_snapshots")
