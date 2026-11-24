from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class CorpusSet(Base):
    """One benchmark corpus: either an account's full output or a topic sample.

    The two kinds answer different questions and must never be mixed:

    * ``account`` — what *this person* sounds like. Comparability comes from a
      single author; the variable under study is "which post did better".
    * ``topic`` — what *works in this subject*. Comparability comes from a shared
      subject across authors; the variable is "who wrote it better".

    Distilling tone from a topic set averages several people into a voice nobody
    has (the failure that produced a "style" made of 平均句长 27.8 字).
    """

    __tablename__ = "corpus_sets"
    __table_args__ = (Index("ix_corpus_sets_user_kind", "user_id", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")

    # account | topic
    kind: Mapped[str] = mapped_column(String(16), default="account", index=True)

    # Populated per kind; kept nullable so the record still says what was asked for.
    platform_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("platform_accounts.id"), nullable=True
    )
    source_accounts: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    keyword: Mapped[str] = mapped_column(String(128), default="")

    # draft | collecting | collected | labelled | failed
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    note: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, onupdate=shanghai_now
    )


class CorpusMember(Base):
    """One note inside a corpus set, with its collection and comparison state.

    ``role`` is a property of the *membership*, not of the note: the same post can
    be a ``baseline`` in its author's account set and a ``negative`` in a topic set
    where that genre underperforms. Storing role on ``notes`` would force a choice.

    ``collect_status`` exists so "we never got this note" can never be mistaken
    for "this note has zero likes" — the defect that left 97 of 104 rows with a
    ``0`` follower count and silently broke the low-follower filter.
    """

    __tablename__ = "corpus_members"
    __table_args__ = (
        Index("uq_corpus_members_set_note", "set_id", "note_id", unique=True),
        Index("ix_corpus_members_set_status", "set_id", "collect_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("corpus_sets.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    # The platform's own id, available even when the body was never collected.
    note_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    note_db_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("notes.id"), nullable=True
    )

    # ok | throttled | deleted | empty_body | pending
    collect_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    collect_error: Mapped[str] = mapped_column(Text, default="")

    # Genre is chosen by a human after collection. ``unclassified`` is an explicit
    # state, never a default guess: a wrong genre silently poisons the negatives.
    genre: Mapped[str] = mapped_column(String(24), default="unclassified", index=True)

    # baseline | negative | neutral | unassigned
    role: Mapped[str] = mapped_column(String(16), default="unassigned", index=True)
    role_reason: Mapped[str] = mapped_column(Text, default="")

    # Position within the crawl, so a resumed run knows where it stopped.
    discover_index: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[str] = mapped_column(String(64), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=shanghai_now, onupdate=shanghai_now
    )
