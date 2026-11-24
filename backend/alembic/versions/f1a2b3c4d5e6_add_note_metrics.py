"""add note engagement metrics and author fans

Revision ID: f1a2b3c4d5e6
Revises: 60cd5c95fde1
Create Date: 2026-10-20 10:00:00.000000
"""
from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '60cd5c95fde1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        multiplier = 1
        if cleaned.endswith("万"):
            multiplier = 10000
            cleaned = cleaned[:-1]
        elif cleaned.lower().endswith("w"):
            multiplier = 10000
            cleaned = cleaned[:-1]
        try:
            return int(float(cleaned) * multiplier)
        except ValueError:
            return 0
    return 0


def _first(raw: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in raw:
            return _as_int(raw.get(key))
    return 0


def _extract(raw_json: Any) -> dict[str, Any]:
    if isinstance(raw_json, str):
        try:
            raw = json.loads(raw_json)
        except (TypeError, ValueError):
            return {}
    elif isinstance(raw_json, dict):
        raw = raw_json
    else:
        return {}

    card: dict[str, Any] = {}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if items and isinstance(items[0], dict):
        item = items[0]
        card = item.get("note_card") if isinstance(item.get("note_card"), dict) else item
    elif isinstance(raw.get("note_card"), dict):
        card = raw["note_card"]

    interact = card.get("interact_info") if isinstance(card.get("interact_info"), dict) else {}
    merged = {**raw, **card, **interact}
    author = card.get("user") if isinstance(card.get("user"), dict) else {}
    if not author and isinstance(raw.get("user"), dict):
        author = raw["user"]

    return {
        "author_id": str(author.get("user_id") or author.get("id") or raw.get("author_id") or ""),
        "likes": _first(merged, ("likes", "liked_count", "like_count", "likedCount")),
        "collects": _first(merged, ("collects", "collected_count", "collect_count", "collectedCount")),
        "comments": _first(merged, ("comments", "comment_count", "commentCount")),
        "shares": _first(merged, ("shares", "share_count", "shareCount")),
    }


def upgrade() -> None:
    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('author_id', sa.String(length=128), server_default='', nullable=False))
        batch_op.add_column(sa.Column('author_fans', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('like_count', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('collect_count', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('comment_count', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('share_count', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('like_fan_ratio', sa.Float(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('engagement_rate', sa.Float(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('metrics_fetched_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_notes_author_id'), ['author_id'], unique=False)

    # Backfill engagement counts for notes saved before this migration.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, raw_json FROM notes")).fetchall()
    for note_id, raw_json in rows:
        metrics = _extract(raw_json)
        if not any(metrics.values()):
            continue
        bind.execute(
            sa.text(
                "UPDATE notes SET author_id = COALESCE(NULLIF(author_id, ''), :author_id), "
                "like_count = :likes, collect_count = :collects, "
                "comment_count = :comments, share_count = :shares WHERE id = :id"
            ),
            {
                "author_id": metrics["author_id"],
                "likes": metrics["likes"],
                "collects": metrics["collects"],
                "comments": metrics["comments"],
                "shares": metrics["shares"],
                "id": note_id,
            },
        )


def downgrade() -> None:
    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notes_author_id'))
        batch_op.drop_column('metrics_fetched_at')
        batch_op.drop_column('engagement_rate')
        batch_op.drop_column('like_fan_ratio')
        batch_op.drop_column('share_count')
        batch_op.drop_column('comment_count')
        batch_op.drop_column('collect_count')
        batch_op.drop_column('like_count')
        batch_op.drop_column('author_fans')
        batch_op.drop_column('author_id')
