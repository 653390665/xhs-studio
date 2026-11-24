"""Turn a browser-captured work list into a Douyin extraction job.

The extension runs inside the douyin.com page because the detail API is behind
Argus (UIFID + request signature). It sends raw work objects here; this module
does the policy work: filter by duration, drop works already collected, and build
the manifest the existing job pipeline consumes.

Keeping the policy here (not in the extension) means a change in what counts as a
usable sample does not require reinstalling the extension.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import DouyinExtractJob, DouyinWork, User
from backend.app.services.douyin_extract_service import create_job


class CaptureError(ValueError):
    pass


def _published_at(create_time: Any) -> str:
    try:
        value = int(create_time)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value, tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def plan_capture(
    db: Session,
    user: User,
    works: Iterable[dict[str, Any]],
    *,
    min_duration: int = 15,
    max_duration: int = 75,
) -> dict[str, Any]:
    """Filter and dedupe captured works. Pure read: no writes."""
    existing = {
        work_id
        for work_id in db.scalars(
            select(DouyinWork.work_id).where(
                DouyinWork.user_id == user.id,
                # Skip anything already in the pipeline, not just finished works.
                # A second capture while the first job is still transcribing would
                # otherwise download the same video again.
                DouyinWork.status != "failed",
            )
        ).all()
    }
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    filtered_invalid = 0
    filtered_duplicate = 0
    filtered_duration = 0
    skipped_existing = 0

    for raw in works:
        work_id = str(raw.get("work_id") or "").strip()
        play = str(raw.get("play") or "").strip()
        if not work_id or not play.startswith("http"):
            filtered_invalid += 1
            continue
        if work_id in seen:
            filtered_duplicate += 1
            continue
        seen.add(work_id)
        if work_id in existing:
            skipped_existing += 1
            continue
        try:
            duration = float(raw.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        # 0 means "the extension could not read it"; do not throw the work away
        # for a missing field, because the extractor will probe it on download.
        if duration and not (min_duration <= duration <= max_duration):
            filtered_duration += 1
            continue
        items.append(
            {
                "work_id": work_id,
                "url": f"https://www.douyin.com/video/{work_id}",
                "media_url": play,
                "title": str(raw.get("desc") or "")[:512],
                "author_name": str(raw.get("author_name") or "")[:128],
                "author_id": str(raw.get("author_sec_uid") or "")[:128],
                "duration_seconds": duration or None,
                "likes": int(raw.get("likes") or 0),
                "published_at": _published_at(raw.get("create_time")),
            }
        )

    return {
        "items": items,
        "total": len(seen),
        "skipped_existing": skipped_existing,
        "filtered_duration": filtered_duration,
        "filtered_duplicate": filtered_duplicate,
        "filtered_invalid": filtered_invalid,
    }


def create_capture_job(
    db: Session,
    user: User,
    *,
    author_name: str,
    author_sec_uid: str,
    works: Iterable[dict[str, Any]],
    min_duration: int = 15,
    max_duration: int = 75,
) -> tuple[DouyinExtractJob, dict[str, Any]]:
    """Plan and create a job that downloads/transcribes only new works."""
    plan = plan_capture(
        db,
        user,
        works,
        min_duration=min_duration,
        max_duration=max_duration,
    )
    if not plan["items"]:
        detail = []
        if plan["skipped_existing"]:
            detail.append(f"{plan['skipped_existing']} 条已采集过")
        if plan["filtered_duration"]:
            detail.append(f"{plan['filtered_duration']} 条超出 {min_duration}–{max_duration} 秒")
        if plan["filtered_duplicate"]:
            detail.append(f"{plan['filtered_duplicate']} 条重复")
        if plan["filtered_invalid"]:
            detail.append(f"{plan['filtered_invalid']} 条缺作品 ID 或媒体地址")
        raise CaptureError(
            "没有可采集的新作品" + (f"（{'，'.join(detail)}）" if detail else "")
        )

    clean_author = (author_name or "抖音作者").strip()[:128]
    for item in plan["items"]:
        item["author_name"] = item["author_name"] or clean_author
        item["author_id"] = item["author_id"] or (author_sec_uid or "")

    job = create_job(
        db,
        user,
        source_type="manifest",
        source=json.dumps(plan["items"], ensure_ascii=False),
        account_name=clean_author,
        fetch_media=True,
        transcribe=True,
        keep_media=True,
        force=False,
    )
    plan["job_id"] = job.id
    return job, plan


__all__ = ["CaptureError", "create_capture_job", "plan_capture"]
