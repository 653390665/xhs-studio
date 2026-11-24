"""Benchmark corpora: collect a comparable set, label its genre, assign roles.

Design rules that the code below enforces rather than documents:

1. **Account sets and topic sets are never mixed.** They answer different
   questions (how this person sounds vs. what works in this subject) and mixing
   them produces a voice that belongs to nobody.

2. **"Not collected" is never written as a data point.** A throttled or deleted
   note keeps a membership row with ``collect_status`` set, and distillation
   reads only ``ok`` rows. Writing a zero instead is the defect that made 97 of
   104 notes look like zero-follower accounts.

3. **Genre is human-assigned.** ``unclassified`` is a real state, not a default
   guess. Negatives are only computed inside a genre, because a 0-like event
   announcement is not evidence of bad copywriting — measured on the current
   library, the event genre sits at a median of 96 likes against 2,239–3,909 for
   everything else.

4. **Role is relative to the set.** The same note can be a baseline in its
   author's set and a negative in a topic set.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.models import CorpusMember, CorpusSet, Note, PlatformAccount, User

SET_KINDS = ("account", "topic", "baseline")

# Genres are deliberately few and mutually exclusive. ``unclassified`` is a
# state, not a bucket to be guessed into.
GENRES = ("experience", "list", "opinion", "event", "recruit", "unclassified")
GENRE_LABELS = {
    "experience": "经验/复盘",
    "list": "清单/合集",
    "opinion": "观点/科普",
    "event": "活动/通知",
    "recruit": "招人/找搭子",
    "unclassified": "未分类",
}

COLLECT_STATUSES = (
    "pending",
    "pending_body",
    "ok",
    "throttled",
    "deleted",
    "empty_body",
)
ROLES = ("baseline", "negative", "neutral", "unassigned")

# Collection limits. Conservative on purpose: an unbounded crawl on one account
# is the most obvious bot signature, and rate limiting currently exists only for
# the monitoring module.
MAX_SOURCE_ACCOUNTS = 10
MAX_PAGES_PER_ACCOUNT = 5
MAX_NOTES_PER_SET = 500

MIN_BASELINE_PER_GENRE = 3

# Same bar as ``style_evidence.MIN_USABLE_CHARS`` and
# ``build_structure_template``: below this a "note" is a title plus a hashtag,
# and measuring its opening/ending would produce fake structure.
MIN_MEMBER_BODY_CHARS = 40
"""A genre needs at least this many collected notes before role assignment is
meaningful. Below it every note would be either "best" or "worst" of two."""


class CorpusError(ValueError):
    """Raised when a corpus operation cannot be honoured."""


# --- Sets -------------------------------------------------------------------


def create_set(
    db: Session,
    user: User,
    *,
    name: str,
    kind: str,
    source_accounts: Iterable[str] | None = None,
    keyword: str = "",
    platform_account_id: int | None = None,
) -> CorpusSet:
    clean_name = (name or "").strip()
    if not clean_name:
        raise CorpusError("请先给对标集起个名字")
    if kind not in SET_KINDS:
        raise CorpusError(f"未知的对标集类型：{kind}")

    sources = [str(item).strip() for item in (source_accounts or []) if str(item).strip()]
    if kind == "account" and not sources and not platform_account_id:
        raise CorpusError("账号集至少要指定一个账号主页链接")
    if len(sources) > MAX_SOURCE_ACCOUNTS:
        raise CorpusError(f"一次最多 {MAX_SOURCE_ACCOUNTS} 个账号，避免风控")
    if kind == "topic" and not (keyword or "").strip():
        raise CorpusError("话题集必须给一个关键词")
    if kind == "baseline":
        if not (keyword or "").strip():
            raise CorpusError("基线集必须给一个赛道标识（keyword）")
        if not sources:
            raise CorpusError("基线集至少要标注一位对照作者")

    record = CorpusSet(
        user_id=user.id,
        name=clean_name[:128],
        kind=kind,
        platform_account_id=platform_account_id,
        source_accounts=sources or None,
        keyword=(keyword or "").strip()[:128],
        status="draft",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_set(db: Session, user: User, set_id: int) -> CorpusSet:
    record = db.get(CorpusSet, set_id)
    if record is None or record.user_id != user.id:
        raise CorpusError("对标集不存在")
    return record


def list_sets(db: Session, user: User, *, kind: str | None = None) -> list[CorpusSet]:
    statement = select(CorpusSet).where(CorpusSet.user_id == user.id)
    if kind in SET_KINDS:
        statement = statement.where(CorpusSet.kind == kind)
    return list(db.scalars(statement.order_by(CorpusSet.created_at.desc())).all())


# --- Members ----------------------------------------------------------------


def upsert_member(
    db: Session,
    user: User,
    corpus_set: CorpusSet,
    *,
    note_id: str,
    note_db_id: int | None = None,
    collect_status: str = "pending",
    collect_error: str = "",
    discover_index: int = 0,
    published_at: str = "",
) -> CorpusMember:
    """Record one discovered note. Never invents metrics for a failed fetch."""
    if collect_status not in COLLECT_STATUSES:
        raise CorpusError(f"未知的采集状态：{collect_status}")
    if not (note_id or "").strip():
        raise CorpusError("note_id 不能为空")

    member = db.scalars(
        select(CorpusMember).where(
            CorpusMember.set_id == corpus_set.id,
            CorpusMember.note_id == note_id,
        )
    ).first()
    if member is None:
        member = CorpusMember(
            set_id=corpus_set.id,
            user_id=user.id,
            note_id=note_id,
            discover_index=discover_index,
        )
        db.add(member)

    if note_db_id is not None:
        member.note_db_id = note_db_id
    member.collect_status = collect_status
    member.collect_error = (collect_error or "")[:1000]
    member.discover_index = discover_index or member.discover_index
    if published_at:
        member.published_at = published_at
    db.commit()
    db.refresh(member)
    return member


def set_genre(
    db: Session,
    user: User,
    member_ids: list[int],
    genre: str,
) -> int:
    """Assign genre to members. Explicit call only — never a default guess."""
    if genre not in GENRES:
        raise CorpusError(f"未知体裁：{genre}")
    rows = db.scalars(
        select(CorpusMember).where(
            CorpusMember.user_id == user.id,
            CorpusMember.id.in_(member_ids or [-1]),
        )
    ).all()
    for row in rows:
        row.genre = genre
        # A genre change invalidates any role computed under the old genre.
        row.role = "unassigned"
        row.role_reason = ""
    db.commit()
    return len(rows)


def _engagement(note: Note) -> int:
    return (
        int(note.like_count or 0)
        + int(note.collect_count or 0)
        + int(note.comment_count or 0)
        + int(note.share_count or 0)
    )


def assign_roles(db: Session, user: User, corpus_set: CorpusSet) -> dict[str, Any]:
    """Split collected members into baseline / negative **within each genre**.

    Rules, all of which exist to avoid a wrong negative:

    * only ``collect_status == "ok"`` members with a linked note are considered;
    * ``unclassified`` members are excluded and reported, never guessed into a genre;
    * a genre needs ``MIN_BASELINE_PER_GENRE`` notes, otherwise every note is
      either the best or the worst of a handful;
    * within a genre, the split is at the median engagement: strictly above is
      ``baseline``, strictly below is ``negative``, exactly at the median is
      ``neutral`` (it is evidence of nothing).
    """
    members = db.scalars(
        select(CorpusMember).where(CorpusMember.set_id == corpus_set.id)
    ).all()

    by_genre: dict[str, list[CorpusMember]] = {}
    skipped_unclassified = 0
    skipped_uncollected = 0
    for member in members:
        if member.collect_status != "ok" or member.note_db_id is None:
            skipped_uncollected += 1
            continue
        if member.genre == "unclassified":
            skipped_unclassified += 1
            continue
        by_genre.setdefault(member.genre, []).append(member)

    report: dict[str, Any] = {
        "set_id": corpus_set.id,
        "genres": {},
        "skipped_unclassified": skipped_unclassified,
        "skipped_uncollected": skipped_uncollected,
    }

    for genre, rows in by_genre.items():
        notes = {
            note.id: note
            for note in db.scalars(
                select(Note).where(Note.id.in_([row.note_db_id for row in rows]))
            ).all()
        }
        scored = [(row, _engagement(notes[row.note_db_id])) for row in rows if row.note_db_id in notes]
        if len(scored) < MIN_BASELINE_PER_GENRE:
            for row, _ in scored:
                row.role = "unassigned"
                row.role_reason = f"该体裁只有 {len(scored)} 篇，少于 {MIN_BASELINE_PER_GENRE} 篇，不判定高低"
            report["genres"][genre] = {
                "label": GENRE_LABELS.get(genre, genre),
                "count": len(scored),
                "baseline": 0,
                "negative": 0,
                "neutral": 0,
                "skipped": "样本不足",
            }
            continue

        cut = median([value for _, value in scored])
        baseline = negative = neutral = 0
        for row, value in scored:
            if value > cut:
                row.role = "baseline"
                row.role_reason = f"互动 {value} 高于本体裁中位数 {cut:.0f}"
                baseline += 1
            elif value < cut:
                row.role = "negative"
                row.role_reason = f"互动 {value} 低于本体裁中位数 {cut:.0f}"
                negative += 1
            else:
                row.role = "neutral"
                row.role_reason = f"互动恰为中位数 {cut:.0f}，不构成证据"
                neutral += 1
        report["genres"][genre] = {
            "label": GENRE_LABELS.get(genre, genre),
            "count": len(scored),
            "median_engagement": cut,
            "baseline": baseline,
            "negative": negative,
            "neutral": neutral,
        }

    corpus_set.status = "labelled"
    db.commit()
    return report


def distillable_members(db: Session, corpus_set: CorpusSet) -> list[CorpusMember]:
    """Members safe to feed a distiller: collected, classified, role-tagged.

    ``collect_status == "ok"`` now means "this row has a body" (see
    ``api/corpus.py``). Listing pages carry no body, so a freshly collected set
    sits in ``pending_body`` until ``collect-bodies`` fills it; those rows are
    excluded here by construction, not by a second content check.

    Anything looser silently includes throttled or body-less rows, which is how
    a missing value becomes a data point.
    """
    return list(
        db.scalars(
            select(CorpusMember).where(
                CorpusMember.set_id == corpus_set.id,
                CorpusMember.collect_status == "ok",
                CorpusMember.note_db_id.is_not(None),
                CorpusMember.genre != "unclassified",
                CorpusMember.role.in_(("baseline", "negative")),
            )
        ).all()
    )


def serialize_set(db: Session, corpus_set: CorpusSet) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(CorpusMember.collect_status, func.count(CorpusMember.id))
            .where(CorpusMember.set_id == corpus_set.id)
            .group_by(CorpusMember.collect_status)
        ).all()
    )
    genre_counts = dict(
        db.execute(
            select(CorpusMember.genre, func.count(CorpusMember.id))
            .where(CorpusMember.set_id == corpus_set.id)
            .group_by(CorpusMember.genre)
        ).all()
    )
    role_counts = dict(
        db.execute(
            select(CorpusMember.role, func.count(CorpusMember.id))
            .where(CorpusMember.set_id == corpus_set.id)
            .group_by(CorpusMember.role)
        ).all()
    )
    shape = corpus_shape(db, corpus_set)
    return {
        "id": corpus_set.id,
        "name": corpus_set.name,
        "kind": corpus_set.kind,
        "keyword": corpus_set.keyword,
        "source_accounts": corpus_set.source_accounts or [],
        "status": corpus_set.status,
        "note": corpus_set.note,
        "total": sum(counts.values()),
        "collect": {status_: counts.get(status_, 0) for status_ in COLLECT_STATUSES},
        "genres": {genre: genre_counts.get(genre, 0) for genre in GENRES},
        "roles": {role: role_counts.get(role, 0) for role in ROLES},
        # Which product this corpus can feed. A corpus of 95 authors cannot
        # produce a writing style (any habit falls far below the 80% bar), but it
        # is exactly the right input for a structure template. Saying this up
        # front turns "0 hard rules, no explanation" into a choice.
        "shape": shape,
        "updated_at": corpus_set.updated_at.isoformat() if corpus_set.updated_at else None,
    }


def corpus_shape(db: Session, corpus_set: CorpusSet) -> dict[str, Any]:
    """Author mix and low-follower breakout count for this corpus.

    Both numbers decide which of the two products this corpus can feed:

    * one author → writing style (``distill_corpus_set``)
    * several authors → content structure (structure template from breakouts)
    """
    from backend.app.services.low_follower import DEFAULT_RULE

    # "Shape" answers what this corpus *can* feed, so it counts every note whose
    # body we actually have — not just rows that already have a genre and a
    # baseline/negative role. Using ``distillable_members`` here made a freshly
    # filled single-author set report "0 位作者" until the user clicked
    # 分配基线/反例, which reads as "this corpus is empty".
    member_rows = db.scalars(
        select(CorpusMember).where(
            CorpusMember.set_id == corpus_set.id,
            CorpusMember.collect_status == "ok",
            CorpusMember.note_db_id.is_not(None),
        )
    ).all()
    note_ids = [m.note_db_id for m in member_rows if m.note_db_id]
    if not note_ids:
        return {
            "authors": 0,
            "notes": 0,
            "single_author": False,
            "fans_measured": 0,
            "breakouts": 0,
            "rule": DEFAULT_RULE.label(),
        }

    notes = {
        note.id: note
        for note in db.scalars(select(Note).where(Note.id.in_(note_ids))).all()
    }
    authors: dict[str, int] = {}
    fans_measured = 0
    breakouts = 0
    for note in notes.values():
        if note.author_name:
            authors[note.author_name] = authors.get(note.author_name, 0) + 1
        if (note.author_fans_status or "unknown") == "known" and int(note.author_fans or 0) > 0:
            fans_measured += 1
            if DEFAULT_RULE.accepts(
                int(note.author_fans or 0),
                int(note.like_count or 0),
                _note_age_days(note),
            ):
                breakouts += 1

    return {
        "authors": len(authors),
        "notes": len(notes),
        "single_author": len(authors) <= 1,
        "fans_measured": fans_measured,
        "breakouts": breakouts,
        "rule": DEFAULT_RULE.label(),
    }


def _note_age_days(note: Note) -> int | None:
    from backend.app.core.time import shanghai_now

    published = getattr(note, "published_at", None)
    if published is None:
        return None
    return max(0, (shanghai_now().date() - published.date()).days)


def serialize_member(member: CorpusMember, note: Note | None = None) -> dict[str, Any]:
    return {
        "id": member.id,
        "note_id": member.note_id,
        "note_db_id": member.note_db_id,
        "collect_status": member.collect_status,
        "collect_error": member.collect_error,
        "genre": member.genre,
        "genre_label": GENRE_LABELS.get(member.genre, member.genre),
        "role": member.role,
        "role_reason": member.role_reason,
        "published_at": member.published_at,
        "title": (note.title if note else "") or "",
        "author_name": (note.author_name if note else "") or "",
        "likes": int(note.like_count or 0) if note else 0,
        "collects": int(note.collect_count or 0) if note else 0,
        "engagement": _engagement(note) if note else 0,
    }


def add_notes_to_set(
    db: Session,
    user: User,
    corpus_set: CorpusSet,
    note_ids: list[int],
    *,
    genre: str | None = None,
) -> dict[str, Any]:
    """Attach existing library notes to a corpus set.

    Account sets used to be the only way to get members, because the only
    producer was ``/collect`` (crawl a profile). A topic set — "what works under
    this keyword" — had no bridge at all: it could be created, but never filled,
    so distillation on it always reported zero notes.

    Bodies already in the library are ``ok`` immediately. Notes whose body is
    shorter than ``MIN_MEMBER_BODY_CHARS`` become ``pending_body``, which is the
    existing state ``/collect-bodies`` knows how to finish. Nothing is guessed:
    a short note is not marked ``ok`` just because it exists.
    """
    wanted = list(dict.fromkeys(int(note_id) for note_id in note_ids))
    if not wanted:
        raise CorpusError("没有选择任何笔记")
    if genre and genre not in GENRES:
        raise CorpusError(f"未知体裁：{genre}")

    notes = {
        note.id: note
        for note in db.scalars(
            select(Note).where(
                Note.user_id == user.id,
                Note.id.in_(wanted),
            )
        ).all()
    }
    missing = [note_id for note_id in wanted if note_id not in notes]
    # Not an error: a note can be deleted while the drawer is open. Report it
    # rather than silently adding fewer rows than the user selected.

    existing = {
        member.note_id
        for member in db.scalars(
            select(CorpusMember).where(CorpusMember.set_id == corpus_set.id)
        ).all()
    }
    total_before = len(existing)
    room = MAX_NOTES_PER_SET - total_before
    to_add = [note for note in notes.values() if note.note_id not in existing]
    if len(to_add) > room:
        raise CorpusError(
            f"这集最多 {MAX_NOTES_PER_SET} 篇，现在已有 {total_before} 篇，"
            f"这次最多还能加 {max(0, room)} 篇。"
        )

    added = skipped = pending = 0
    for note in to_add:
        body = (note.content or "").strip()
        has_body = len(body) >= MIN_MEMBER_BODY_CHARS
        member = upsert_member(
            db,
            user,
            corpus_set,
            note_id=note.note_id,
            note_db_id=note.id,
            collect_status="ok" if has_body else "pending_body",
            collect_error="" if has_body else "来自素材库，正文不足，待补",
            discover_index=total_before + added,
            published_at=note.published_at.isoformat() if note.published_at else "",
        )
        if genre:
            # Explicit choice only. ``unclassified`` stays the default so the
            # distiller never treats a guess as a fact.
            member.genre = genre
            member.role = "unassigned"
            member.role_reason = ""
        added += 1
        if not has_body:
            pending += 1

    skipped = len(notes) - added
    if added:
        corpus_set.status = "collected" if corpus_set.status == "draft" else corpus_set.status
    db.commit()

    return {
        "added": added,
        "pending_body": pending,
        "skipped_already_in_set": skipped,
        "missing_note_ids": missing,
        "set": serialize_set(db, corpus_set),
    }


def delete_set(db: Session, corpus_set: CorpusSet) -> None:
    """Delete the set and its memberships, leaving the notes untouched."""
    db.execute(delete(CorpusMember).where(CorpusMember.set_id == corpus_set.id))
    db.delete(corpus_set)
    db.commit()


def remove_member(db: Session, user: User, corpus_set: CorpusSet, member_id: int) -> None:
    member = db.scalars(
        select(CorpusMember).where(
            CorpusMember.id == member_id,
            CorpusMember.set_id == corpus_set.id,
            CorpusMember.user_id == user.id,
        )
    ).first()
    if member is None:
        raise CorpusError("这集里没有这条笔记")
    db.delete(member)
    db.commit()


__all__ = [
    "SET_KINDS",
    "GENRES",
    "GENRE_LABELS",
    "COLLECT_STATUSES",
    "ROLES",
    "MAX_SOURCE_ACCOUNTS",
    "MAX_PAGES_PER_ACCOUNT",
    "MAX_NOTES_PER_SET",
    "MIN_BASELINE_PER_GENRE",
    "MIN_MEMBER_BODY_CHARS",
    "CorpusError",
    "create_set",
    "get_set",
    "list_sets",
    "upsert_member",
    "add_notes_to_set",
    "remove_member",
    "delete_set",
    "set_genre",
    "assign_roles",
    "distillable_members",
    "serialize_set",
    "serialize_member",
]
