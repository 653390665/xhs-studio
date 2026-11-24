"""The one definition of "this note belongs to the account".

Four implementations of this rule existed, and two of them were wrong:

* ``skill_evolution_service`` filtered on ``platform_account_id`` alone, so the
  104 crawled competitor notes counted as "the account's own notes". That made
  ``len(scorable_account) >= 10`` always true and the evolution report claim
  样本来自当前账号的笔记 while mixing in strangers' posts.
* ``agent_service._account_notes`` and ``accounts._account_notes`` used
  ``author_id == external OR platform_account_id == id``. The OR is the bug: a
  crawled note is stored under the same ``platform_account_id`` as the user's own
  posts, so the second branch matches everything.

``analytics._is_own_note`` was correct. It is the reference implementation, moved
here so every caller shares it.

The rule, in order:

1. ``source_type`` in ``creator`` / ``publish`` — written by our own paths.
2. legacy rows before ``source_type`` existed: ``raw_json.origin == "publish"``
   or ``raw_json.source == "creator_published"``.

``platform_account_id`` is deliberately **not** used: it records which login was
active when the row was written, not who wrote the post.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models import Note, PlatformAccount, User

OWN_SOURCE_TYPES: tuple[str, ...] = ("creator", "publish")


def is_own_note(note: Note) -> bool:
    """True when the note was written by the account, not collected from others."""
    if note is None:
        return False
    if (note.source_type or "") in OWN_SOURCE_TYPES:
        return True
    raw = note.raw_json if isinstance(note.raw_json, dict) else {}
    return raw.get("origin") == "publish" or raw.get("source") == "creator_published"


def own_notes_statement(user_id: int):
    """SQL condition for own notes. Use this instead of ``platform_account_id``."""
    return select(Note).where(
        Note.user_id == user_id,
        Note.platform == "xhs",
        Note.source_type.in_(OWN_SOURCE_TYPES),
    )


def own_notes(db: Session, user: User, account_id: int | None = None) -> list[Note]:
    """The account's own notes.

    ``account_id`` narrows by account **only after** the source-type filter, so a
    crawled note can never survive on its account id alone.
    """
    statement = own_notes_statement(user.id)
    if account_id is not None:
        statement = statement.where(Note.platform_account_id == account_id)
    return list(db.scalars(statement.order_by(Note.created_at.desc())).all())


def count_own_notes(db: Session, user: User, account_id: int | None = None) -> int:
    return len(own_notes(db, user, account_id))


def library_notes(db: Session, user: User) -> list[Note]:
    """Everything collected rather than written: the benchmark sample pool."""
    statement = select(Note).where(
        Note.user_id == user.id,
        Note.platform == "xhs",
        Note.source_type.not_in(OWN_SOURCE_TYPES),
    )
    return list(db.scalars(statement.order_by(Note.created_at.desc())).all())


def filter_own(notes: Iterable[Note]) -> list[Note]:
    """Filter an already-loaded list. For callers that cannot push down to SQL."""
    return [note for note in notes if is_own_note(note)]


__all__ = [
    "OWN_SOURCE_TYPES",
    "is_own_note",
    "own_notes_statement",
    "own_notes",
    "count_own_notes",
    "library_notes",
    "filter_own",
]
