"""Publish feedback loop: write a successfully published job back into the library.

The library powers 内容库 / 数据洞察 / 爆款模板, so without this step a note that
was just published is invisible to the rest of the product. The note is marked
with ``raw_json.origin == "publish"`` and can later be refreshed by re-saving the
same ``note_id`` through discovery or the crawler.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Note, NoteAsset, PlatformAccount, PublishAsset, PublishJob
from backend.app.services.account_service import profile_fans


def _asset_fields(file_path: str) -> dict[str, str]:
    """Map a publish asset path to the note-asset (url, local_path) pair."""
    value = (file_path or "").strip()
    if value.startswith("/api/files/media/"):
        return {"url": "", "local_path": value.rsplit("/", 1)[-1]}
    if value.startswith("http://") or value.startswith("https://"):
        return {"url": value, "local_path": ""}
    return {}


def _profile_fans(account: PlatformAccount | None) -> int:
    if account is None:
        return 0
    return profile_fans(account.profile_json)


def save_published_note(
    db: Session,
    job: PublishJob,
    account: PlatformAccount | None = None,
) -> Note | None:
    """Upsert a published job into ``notes``; returns None when the id is unknown.

    Callers must commit the session. The function is idempotent: running it twice
    for the same job updates the same row instead of duplicating it.
    """
    external_id = (job.external_note_id or "").strip()
    if not external_id:
        return None
    if account is None and job.platform_account_id:
        account = db.get(PlatformAccount, job.platform_account_id)

    note = db.scalars(
        select(Note).where(
            Note.user_id == job.user_id,
            Note.platform == job.platform,
            Note.note_id == external_id,
        )
    ).first()

    if note is None:
        note = Note(
            user_id=job.user_id,
            platform_account_id=job.platform_account_id or 0,
            platform=job.platform,
            note_id=external_id,
            source_type="publish",
            title=job.title or "",
            content=job.body or "",
            author_name=(account.nickname if account else "") or "",
            author_id=(account.external_user_id if account else "") or "",
            author_fans=_profile_fans(account),
            raw_json={},
        )
        db.add(note)
        db.flush()
    else:
        note.source_type = "publish"
        if job.title:
            note.title = job.title
        if job.body:
            note.content = job.body

    note_url = f"https://www.xiaohongshu.com/explore/{external_id}"
    raw = dict(note.raw_json or {})
    raw.update(
        {
            "origin": "publish",
            "publish_job_id": job.id,
            "note_url": note_url,
            "published_at": job.published_at.isoformat() if job.published_at else "",
        }
    )
    note.raw_json = raw

    existing_assets = db.scalars(select(NoteAsset).where(NoteAsset.note_id == note.id)).all()
    seen = {asset.local_path or asset.url for asset in existing_assets}
    order = max((asset.sort_order for asset in existing_assets), default=-1) + 1

    publish_assets = db.scalars(
        select(PublishAsset).where(PublishAsset.publish_job_id == job.id).order_by(PublishAsset.id.asc())
    ).all()
    for asset in publish_assets:
        if asset.asset_type not in {"image", "video"}:
            continue
        fields = _asset_fields(asset.file_path)
        if not fields:
            continue
        key = fields["local_path"] or fields["url"]
        if key in seen:
            continue
        db.add(
            NoteAsset(
                note_id=note.id,
                asset_type=asset.asset_type,
                sort_order=order,
                url=fields["url"],
                local_path=fields["local_path"],
            )
        )
        seen.add(key)
        order += 1

    from backend.app.services.memory_service import record_publish_performance

    record_publish_performance(
        db,
        user_id=job.user_id,
        account_id=job.platform_account_id,
        note_id=external_id,
        title=job.title or note.title,
        job_id=job.id,
        published_at=job.published_at.isoformat() if job.published_at else "",
    )
    return note


__all__ = ["save_published_note"]
