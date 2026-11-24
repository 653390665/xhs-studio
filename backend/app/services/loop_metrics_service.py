from __future__ import annotations

from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import shanghai_now
from backend.app.models import AiDraft, Note, PublishJob, User

LOOP_ORIGIN_LABELS = {
    "manual": "手动",
    "ai": "AI 生成",
    "ai_image": "图片生成",
    "agent": "智能助手",
    "matrix": "多账号版本",
    "batch_rewrite": "批量改写",
    "batch_create": "批量建草稿",
    "auto_ops": "按关键词定时生成",
}


def compute_loop_metrics(
    db: Session,
    user: User,
    *,
    days: int = 7,
    account_id: int | None = None,
) -> dict:
    since = shanghai_now() - timedelta(days=days)

    draft_statement = select(AiDraft).where(
        AiDraft.user_id == user.id,
        AiDraft.created_at >= since,
    )
    job_statement = select(PublishJob).where(
        PublishJob.user_id == user.id,
        PublishJob.created_at >= since,
    )
    note_statement = select(Note).where(
        Note.user_id == user.id,
        Note.source_type.in_(("creator", "publish")),
    )
    if account_id is not None:
        draft_statement = draft_statement.where(AiDraft.platform_account_id == account_id)
        job_statement = job_statement.where(PublishJob.platform_account_id == account_id)
        note_statement = note_statement.where(Note.platform_account_id == account_id)

    drafts = db.scalars(draft_statement).all()
    jobs = db.scalars(job_statement).all()
    own_notes = db.scalars(note_statement).all()

    published = [job for job in jobs if job.status == "published"]
    failed = [job for job in jobs if job.status == "failed"]
    finished = len(published) + len(failed)
    refreshed = [
        note
        for note in own_notes
        if note.metrics_fetched_at is not None and note.metrics_fetched_at >= since
    ]
    origin_counts = Counter((draft.origin or "manual") for draft in drafts)
    skill_counts = Counter((job.skill_version or "未记录") for job in published)
    pillar_counts = Counter((job.pillar or "未标注") for job in published)

    # A "closed loop" note needs both a published job and a later metric refresh.
    # Counting either alone would overstate: a draft that never shipped, or a
    # refresh on an old note, are not this week's closed work.
    published_note_ids = {
        job.external_note_id for job in published if job.external_note_id
    }
    refreshed_ids = {note.note_id for note in refreshed}
    if published_note_ids:
        closed_notes = [
            note for note in own_notes if note.note_id in published_note_ids
        ]
    else:
        # Older jobs may not carry external_note_id; fall back to "published this
        # window AND refreshed this window" so the number stays meaningful.
        closed_notes = [
            note for note in refreshed if note.note_id in refreshed_ids
        ] if published else []

    return {
        "window_days": days,
        "since": since.isoformat(),
        "closed_loop_count": len(closed_notes),
        "drafts_created": len(drafts),
        "drafts_reviewed": sum(1 for draft in drafts if (draft.review_status or "pending") != "pending"),
        "drafts_adopted": sum(1 for draft in drafts if draft.review_status == "adopted"),
        "jobs_created": len(jobs),
        "jobs_scheduled": sum(
            1 for job in jobs if job.publish_mode == "scheduled" and job.status in {"pending", "scheduled", "publishing"}
        ),
        "jobs_published": len(published),
        "jobs_failed": len(failed),
        "publish_success_rate": round(len(published) / finished * 100, 1) if finished else None,
        "own_notes": len(own_notes),
        "own_notes_refreshed": len(refreshed),
        "refresh_rate": round(len(refreshed) / len(own_notes) * 100, 1) if own_notes else None,
        "by_origin": [
            {"origin": origin, "label": LOOP_ORIGIN_LABELS.get(origin, origin), "count": count}
            for origin, count in origin_counts.most_common()
        ],
        "by_skill_version": [
            {"version": version, "count": count}
            for version, count in skill_counts.most_common()
        ],
        "by_pillar": [
            {"pillar": pillar, "count": count}
            for pillar, count in pillar_counts.most_common()
        ],
    }
