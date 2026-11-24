"""add corpus sets

Revision ID: l5a6b7c8d9e0
Revises: k4f5a6b7c8d9
Create Date: 2026-10-27 10:30:00.000000

Two tables instead of columns on ``notes``:

* a post can belong to both an account set and a topic set, so membership is a
  relation, not an attribute;
* the baseline/negative role is relative to the set (a post can be the best in
  its author's set and a poor example in a genre comparison), so it cannot live
  on the note either.

``collect_status`` separates "not collected" from "collected and genuinely low",
which is the defect that made 97 of 104 notes look like zero-follower accounts.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'l5a6b7c8d9e0'
down_revision: Union[str, None] = 'k4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'corpus_sets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default='account'),
        sa.Column('platform_account_id', sa.Integer(), nullable=True),
        sa.Column('source_accounts', sa.JSON(), nullable=True),
        sa.Column('keyword', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='draft'),
        sa.Column('note', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['platform_account_id'], ['platform_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_corpus_sets_user_id', 'corpus_sets', ['user_id'])
    op.create_index('ix_corpus_sets_kind', 'corpus_sets', ['kind'])
    op.create_index('ix_corpus_sets_status', 'corpus_sets', ['status'])
    op.create_index('ix_corpus_sets_user_kind', 'corpus_sets', ['user_id', 'kind'])

    op.create_table(
        'corpus_members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('set_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('note_id', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('note_db_id', sa.Integer(), nullable=True),
        sa.Column('collect_status', sa.String(length=24), nullable=False, server_default='pending'),
        sa.Column('collect_error', sa.Text(), nullable=False, server_default=''),
        sa.Column('genre', sa.String(length=24), nullable=False, server_default='unclassified'),
        sa.Column('role', sa.String(length=16), nullable=False, server_default='unassigned'),
        sa.Column('role_reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('discover_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('published_at', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['set_id'], ['corpus_sets.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['note_db_id'], ['notes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_corpus_members_set_id', 'corpus_members', ['set_id'])
    op.create_index('ix_corpus_members_user_id', 'corpus_members', ['user_id'])
    op.create_index('ix_corpus_members_note_id', 'corpus_members', ['note_id'])
    op.create_index('ix_corpus_members_collect_status', 'corpus_members', ['collect_status'])
    op.create_index('ix_corpus_members_genre', 'corpus_members', ['genre'])
    op.create_index('ix_corpus_members_role', 'corpus_members', ['role'])
    op.create_index(
        'uq_corpus_members_set_note', 'corpus_members', ['set_id', 'note_id'], unique=True
    )
    op.create_index(
        'ix_corpus_members_set_status', 'corpus_members', ['set_id', 'collect_status']
    )


def downgrade() -> None:
    op.drop_index('ix_corpus_members_set_status', table_name='corpus_members')
    op.drop_index('uq_corpus_members_set_note', table_name='corpus_members')
    op.drop_index('ix_corpus_members_role', table_name='corpus_members')
    op.drop_index('ix_corpus_members_genre', table_name='corpus_members')
    op.drop_index('ix_corpus_members_collect_status', table_name='corpus_members')
    op.drop_index('ix_corpus_members_note_id', table_name='corpus_members')
    op.drop_index('ix_corpus_members_user_id', table_name='corpus_members')
    op.drop_index('ix_corpus_members_set_id', table_name='corpus_members')
    op.drop_table('corpus_members')
    op.drop_index('ix_corpus_sets_user_kind', table_name='corpus_sets')
    op.drop_index('ix_corpus_sets_status', table_name='corpus_sets')
    op.drop_index('ix_corpus_sets_kind', table_name='corpus_sets')
    op.drop_index('ix_corpus_sets_user_id', table_name='corpus_sets')
    op.drop_table('corpus_sets')
