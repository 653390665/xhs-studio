"""add distill batches and draft generation context

Why three changes at once:

1. ``distill_batches`` / ``distill_batch_items`` — the workbench's four Markdown
   templates used to live only in ``localStorage``. Clearing site data or moving
   to another browser lost every batch, and the writing page had nothing to
   point at.
2. ``ai_drafts.batch_id`` — a draft needs to say which batch it was written
   from, otherwise "regenerate with another batch" has nothing to compare.
3. ``ai_drafts.context_json`` — ``skill_version="style-16"`` is not an answer to
   "why does this draft read like this". The full prompt context (style name and
   revision, template, batch, skill ids, positioning revision) is captured at
   generation time; it cannot be reconstructed later.

Every column is nullable: existing rows predate the feature and must keep
working. ``batch_id`` is intentionally not ``NOT NULL`` — a draft written
without a batch is valid.

Revision ID: r3b4c5d6e7f8
Revises: q1f2a3b4c5d6
Create Date: 2026-11-13 09:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "r3b4c5d6e7f8"
down_revision: Union[str, None] = "q1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return table in sa.inspect(bind).get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    if not _table_exists("distill_batches"):
        op.create_table(
            "distill_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False, server_default=""),
            sa.Column(
                "source_set_id",
                sa.Integer(),
                sa.ForeignKey("corpus_sets.id"),
                nullable=True,
            ),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_distill_batches_user_id", "distill_batches", ["user_id"])
        op.create_index(
            "ix_distill_batches_source_set_id", "distill_batches", ["source_set_id"]
        )
        op.create_index(
            "ix_distill_batches_user_created", "distill_batches", ["user_id", "created_at"]
        )

    if not _table_exists("distill_batch_items"):
        op.create_table(
            "distill_batch_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "batch_id",
                sa.Integer(),
                sa.ForeignKey("distill_batches.id"),
                nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="full"),
            sa.Column("title", sa.String(length=256), nullable=False, server_default=""),
            sa.Column("body_md", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_distill_batch_items_batch_id", "distill_batch_items", ["batch_id"])
        op.create_index("ix_distill_batch_items_user_id", "distill_batch_items", ["user_id"])
        op.create_index(
            "uq_distill_batch_items_kind", "distill_batch_items", ["batch_id", "kind"], unique=True
        )

    if not _has_column("ai_drafts", "batch_id"):
        op.add_column("ai_drafts", sa.Column("batch_id", sa.Integer(), nullable=True))
        op.create_index("ix_ai_drafts_batch_id", "ai_drafts", ["batch_id"])

    if not _has_column("ai_drafts", "context_json"):
        op.add_column("ai_drafts", sa.Column("context_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    if _has_column("ai_drafts", "context_json"):
        op.drop_column("ai_drafts", "context_json")
    if _has_column("ai_drafts", "batch_id"):
        op.drop_index("ix_ai_drafts_batch_id", table_name="ai_drafts")
        op.drop_column("ai_drafts", "batch_id")
    if _table_exists("distill_batch_items"):
        op.drop_table("distill_batch_items")
    if _table_exists("distill_batches"):
        op.drop_table("distill_batches")
