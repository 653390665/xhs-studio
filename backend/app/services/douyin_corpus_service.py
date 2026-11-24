"""Turn a finished Douyin extraction job into a corpus set.

The extraction job writes transcripts to disk (`DouyinWork` rows plus JSON files)
while style distillation reads `corpus_sets` → `corpus_members` → `notes`. Those
two halves were not connected: a job could finish with ten transcripts and the
evidence distiller would still see nothing, so the only way through was a
one-off script.

This module is that missing link, and it is deliberately idempotent: importing
the same job twice updates the note bodies and adds nothing twice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    CorpusMember,
    CorpusSet,
    DouyinExtractJob,
    DouyinWork,
    Note,
    PlatformAccount,
    User,
)
from backend.app.services.douyin_extract_service import _load_transcript_payload


class DouyinCorpusError(ValueError):
    """A job cannot be imported: nothing was transcribed, or a row is invalid."""


def _transcript_dir(job: DouyinExtractJob) -> Path:
    return Path(job.output_dir or "") / "采集记录" / "transcripts"


def _text_for(job: DouyinExtractJob, work: DouyinWork) -> tuple[str, str]:
    """Return (text, engine) for one work, or ("", "") when nothing was produced."""
    payload = _load_transcript_payload(_transcript_dir(job), work.work_id)
    text = str(payload.get("text") or "").strip()
    engine = str(payload.get("engine") or work.transcript_source or "")
    if not text:
        # A manifest may carry the text directly (share-copy imports).
        text = str((work.raw_json or {}).get("transcript") or "").strip()
        engine = engine or "provided"
    return text, engine


def _pick_carrier_account(db: Session, user: User) -> int | None:
    """The account row douyin notes attach to.

    ``notes.platform_account_id`` is non-nullable, and the existing 147 Douyin
    notes all sit on the user's first account. Keeping that convention means a
    Douyin note shows up wherever Douyin notes already show up.
    """
    account = db.scalar(
        select(PlatformAccount)
        .where(PlatformAccount.user_id == user.id)
        .order_by(PlatformAccount.id.asc())
    )
    return account.id if account else None


def _upsert_note(
    db: Session,
    user: User,
    work: DouyinWork,
    *,
    text: str,
    engine: str,
    platform_account_id: int,
) -> tuple[Note, bool]:
    note = db.scalar(
        select(Note).where(
            Note.user_id == user.id,
            Note.platform == "douyin",
            Note.note_id == work.work_id,
        )
    )
    created = note is None
    if note is None:
        note = Note(
            user_id=user.id,
            platform="douyin",
            platform_account_id=platform_account_id,
            note_id=work.work_id,
        )
        db.add(note)

    raw = work.raw_json or {}
    note.title = work.title or note.title or ""
    note.content = text
    note.author_name = work.author_name or note.author_name or ""
    note.author_id = work.author_id or note.author_id or ""
    note.like_count = int(raw.get("likes") or raw.get("digg_count") or note.like_count or 0)
    note.source_type = "douyin_extract"
    # 发布时间同时写列。
    #
    # 列表接口、`published_within_days`、低粉窗口只读 `note.published_at`；
    # 只写 raw 的话，导入的转写稿在「发布」列永远是「—」，按时间筛整批漏掉。
    # 只在 NULL 时写，重复导入不覆盖已解析的值。
    if note.published_at is None and work.published_at:
        from backend.app.services.note_metrics_service import parse_published_at

        parsed = parse_published_at(work.published_at)
        if parsed is not None:
            note.published_at = parsed
    note.raw_json = {
        **(note.raw_json or {}),
        "work_id": work.work_id,
        "job_id": work.job_id,
        "url": work.url,
        "engine": engine,
        "duration_seconds": work.duration_seconds,
        "published_at": work.published_at,
    }
    return note, created


def import_job_as_corpus(
    db: Session,
    user: User,
    job: DouyinExtractJob,
    *,
    name: str = "",
    genre: str = "opinion",
    role: str = "baseline",
    platform_account_id: int | None = None,
    set_id: int | None = None,
) -> dict[str, Any]:
    """Create (or extend) one corpus set from the job's transcribed works.

    Only works that actually produced text are imported. A failed download or a
    silent video is *missing*, never an empty note — an empty body would let a
    detector score zero and call it evidence.
    """
    works = list(
        db.scalars(
            select(DouyinWork).where(DouyinWork.job_id == job.id).order_by(DouyinWork.id.asc())
        ).all()
    )
    prepared = []
    missing = []
    for work in works:
        text, engine = _text_for(job, work)
        if not text:
            missing.append(work.work_id)
            continue
        prepared.append((work, text, engine))

    if not prepared:
        raise DouyinCorpusError(
            "这个任务还没有可导入的文稿：先完成转写，再导入对标集。"
        )

    carrier = platform_account_id or _pick_carrier_account(db, user)
    if not carrier:
        raise DouyinCorpusError("没有可用的小红书账号来挂载抖音笔记（notes.platform_account_id 不能为空）。")

    author = next((w.author_name for w, _, _ in prepared if w.author_name), "") or job.account_name
    options = dict(job.options or {})
    corpus_set: CorpusSet | None = None
    if set_id is not None:
        corpus_set = db.get(CorpusSet, set_id)
        if corpus_set is None or corpus_set.user_id != user.id:
            raise DouyinCorpusError("对标集不存在")
    elif options.get("corpus_set_id"):
        corpus_set = db.get(CorpusSet, int(options["corpus_set_id"]))
        if corpus_set is not None and corpus_set.user_id != user.id:
            corpus_set = None
    if corpus_set is None:
        corpus_set = CorpusSet(
            user_id=user.id,
            name=(name or f"{author or '抖音'} · 抖音采集 #{job.id}")[:128],
            kind="account",
            source_accounts=[author] if author else None,
            status="draft",
        )
        db.add(corpus_set)
        db.flush()
    elif name:
        corpus_set.name = name[:128]
    job.options = {**options, "corpus_set_id": corpus_set.id}

    created_notes = 0
    added_members = 0
    for index, (work, text, engine) in enumerate(prepared):
        note, created = _upsert_note(
            db,
            user,
            work,
            text=text,
            engine=engine,
            platform_account_id=carrier,
        )
        db.flush()
        created_notes += int(created)

        member = db.scalar(
            select(CorpusMember).where(
                CorpusMember.set_id == corpus_set.id,
                CorpusMember.note_id == work.work_id,
            )
        )
        if member is None:
            member = CorpusMember(
                set_id=corpus_set.id,
                user_id=user.id,
                note_id=work.work_id,
                discover_index=index,
            )
            db.add(member)
            added_members += 1
        member.note_db_id = note.id
        member.collect_status = "ok"
        member.collect_error = ""
        member.genre = genre
        member.role = role
        member.published_at = work.published_at or ""

    corpus_set.status = "labelled"
    db.commit()
    db.refresh(corpus_set)
    return {
        "set_id": corpus_set.id,
        "set_name": corpus_set.name,
        "genre": genre,
        "role": role,
        "imported": len(prepared),
        "new_notes": created_notes,
        "new_members": added_members,
        "missing": missing,
        "author": author,
    }


__all__ = ["DouyinCorpusError", "import_job_as_corpus"]
