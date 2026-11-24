from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import to_shanghai_naive
from backend.app.models import PlatformAccount, PublishAsset, PublishJob, Task, User
from backend.app.schemas.common import paginated
from backend.app.schemas.serializers import (
    serialize_publish_job as _shared_serialize_publish_job,
)
from backend.app.services.publish_asset_service import extract_creator_media_id
from backend.app.services.publish_options_service import clean_topics, parse_publish_options
from backend.app.services.publish_preflight_service import preflight_publish_job
from backend.app.services.publish_service import (
    PublishConflictError,
    PublishError,
    PublishNotFoundError,
    PublishPlatformError,
    PublishService,
    PublishUploadError,
    PublishValidationError,
)
from backend.app.services.publish_queue_service import publish_job_counts

router = APIRouter(prefix="/publish", tags=["publish"])
logger = logging.getLogger(__name__)


class PublishJobUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=256)
    body: Optional[str] = None
    platform_account_id: Optional[int] = None
    publish_mode: Optional[str] = Field(default=None, pattern="^(immediate|scheduled)$")
    scheduled_at: Optional[datetime] = None
    topics: Optional[list[str]] = None
    location: Optional[str] = None
    privacy_type: Optional[int] = Field(default=None, ge=0, le=1)
    is_private: Optional[bool] = None


class PublishAssetCreateRequest(BaseModel):
    asset_type: str = Field(pattern="^(image|video)$")
    file_path: str = Field(min_length=1)


def get_creator_publish_adapter_factory():
    return XhsCreatorApiAdapter


def _clean_topics(topics: Optional[list[str]]) -> list[str]:
    return clean_topics(topics)


def _load_publish_options(job: PublishJob) -> dict[str, Any]:
    return parse_publish_options(job.publish_options)


def _store_publish_options(job: PublishJob, options: dict[str, Any]) -> None:
    job.publish_options = json.dumps(options, ensure_ascii=False, separators=(",", ":"))


def _update_publish_options(job: PublishJob, payload: PublishJobUpdateRequest) -> None:
    fields = payload.model_fields_set
    if not {"topics", "location", "privacy_type", "is_private"} & fields:
        return

    options = _load_publish_options(job)
    if "topics" in fields:
        topics = _clean_topics(payload.topics)
        if topics:
            options["topics"] = topics
        else:
            options.pop("topics", None)
    if "location" in fields:
        if payload.location and payload.location.strip():
            options["location"] = payload.location.strip()
        else:
            options.pop("location", None)
    if "is_private" in fields:
        if payload.is_private is None:
            options.pop("is_private", None)
            options.pop("privacy_type", None)
        else:
            options["is_private"] = payload.is_private
            options["privacy_type"] = 1 if payload.is_private else 0
    elif "privacy_type" in fields:
        if payload.privacy_type is None:
            options.pop("privacy_type", None)
            options.pop("is_private", None)
        else:
            options["privacy_type"] = payload.privacy_type
            options["is_private"] = payload.privacy_type == 1
    _store_publish_options(job, options)


def serialize_publish_job(job: PublishJob) -> dict:
    """Alias kept for the call sites in this file; see ``schemas/serializers.py``."""
    return _shared_serialize_publish_job(job)


def serialize_publish_asset(asset: PublishAsset) -> dict:
    try:
        creator_upload_info = json.loads(asset.creator_upload_info or "{}")
    except json.JSONDecodeError:
        creator_upload_info = {}
    return {
        "id": asset.id,
        "publish_job_id": asset.publish_job_id,
        "asset_type": asset.asset_type,
        "file_path": asset.file_path,
        "upload_status": asset.upload_status,
        "creator_media_id": asset.creator_media_id,
        "upload_error": asset.upload_error,
        "creator_upload_info": creator_upload_info,
    }


def _get_owned_publish_job(db: Session, current_user: User, job_id: int) -> PublishJob:
    job = db.scalars(
        select(PublishJob)
        .where(PublishJob.id == job_id, PublishJob.user_id == current_user.id)
    ).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish job not found")
    return job


def _get_owned_publish_asset(db: Session, current_user: User, asset_id: int) -> PublishAsset:
    asset = db.scalars(
        select(PublishAsset)
        .join(PublishJob, PublishAsset.publish_job_id == PublishJob.id)
        .where(
            PublishAsset.id == asset_id,
            PublishJob.user_id == current_user.id,
        )
    ).first()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish asset not found")
    return asset


def _get_latest_account_cookies(db: Session, account_id: int) -> str:
    from backend.app.services.account_cookies import latest_cookies

    try:
        return latest_cookies(db, account_id, missing_detail="Account has no cookies")
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


def _record_publish_control_task(db: Session, current_user: User, job: PublishJob, task_type: str) -> None:
    task = Task(
        user_id=current_user.id,
        platform=job.platform,
        task_type=task_type,
        status="pending",
        progress=0,
        payload={
            "publish_job_id": job.id,
            "platform_account_id": job.platform_account_id,
            "publish_mode": job.publish_mode,
        },
    )
    db.add(task)


@router.get("/jobs")
def get_publish_jobs(
    platform: Optional[str] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = (
        select(PublishJob)
        .where(PublishJob.user_id == current_user.id)
    )
    if platform:
        statement = statement.where(PublishJob.platform == platform)
    if status and status != "all":
        statement = statement.where(PublishJob.status == status)
    if start is not None or end is not None:
        start_dt = datetime.combine(start, time.min) if start is not None else None
        end_dt = datetime.combine(end + timedelta(days=1), time.min) if end is not None else None
        range_clauses = []
        if start_dt is not None and end_dt is not None:
            range_clauses.append(and_(PublishJob.scheduled_at >= start_dt, PublishJob.scheduled_at < end_dt))
            range_clauses.append(and_(PublishJob.published_at >= start_dt, PublishJob.published_at < end_dt))
            range_clauses.append(
                and_(
                    PublishJob.scheduled_at.is_(None),
                    PublishJob.published_at.is_(None),
                    PublishJob.created_at >= start_dt,
                    PublishJob.created_at < end_dt,
                )
            )
        elif start_dt is not None:
            range_clauses.append(PublishJob.scheduled_at >= start_dt)
            range_clauses.append(PublishJob.published_at >= start_dt)
            range_clauses.append(
                and_(
                    PublishJob.scheduled_at.is_(None),
                    PublishJob.published_at.is_(None),
                    PublishJob.created_at >= start_dt,
                )
            )
        else:
            range_clauses.append(PublishJob.scheduled_at < end_dt)
            range_clauses.append(PublishJob.published_at < end_dt)
            range_clauses.append(
                and_(
                    PublishJob.scheduled_at.is_(None),
                    PublishJob.published_at.is_(None),
                    PublishJob.created_at < end_dt,
                )
            )
        statement = statement.where(or_(*range_clauses))
    jobs = db.scalars(statement.order_by(PublishJob.created_at.desc(), PublishJob.id.desc())).all()
    # 统计必须整表算，不能数这一页。
    # 以前前端在 `items`（后端分页后的 20 条）上 count，第 21 条起不进统计，
    # 于是队列显示「待确认 3 条」而下方列表里有 8 条。数字和列表互相打架时，
    # 用户只能怀疑数据坏了。
    #
    # 统计也不受 `status` 筛选影响：筛「失败」时仍要看到「待确认 8 条」，
    # 否则一筛选就以为队列空了。
    counts = publish_job_counts(db, current_user, platform=platform)
    # ``max_size`` 必须和路由声明的 ``le=500`` 一致。共享分页器默认 100，
    # 于是 130 条待确认时列表只给 100 行，第 101 条起点不到、也发不了，
    # 而 counts 仍说 130 —— 数字和列表互相打架。
    return paginated(
        [serialize_publish_job(job) for job in jobs],
        page,
        page_size,
        extra={"counts": counts},
        max_size=500,
    )


@router.get("/jobs/{job_id}")
def get_publish_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return serialize_publish_job(_get_owned_publish_job(db, current_user, job_id))


@router.get("/jobs/{job_id}/preflight")
def publish_job_preflight(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    return preflight_publish_job(db, current_user, job)


@router.patch("/jobs/{job_id}")
def update_publish_job(
    job_id: int,
    payload: PublishJobUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    if payload.platform_account_id is not None:
        account = db.get(PlatformAccount, payload.platform_account_id)
        if account is None or account.user_id != current_user.id or account.platform != job.platform:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform account not found")
        job.platform_account_id = account.id
    if payload.title is not None:
        job.title = payload.title
    if payload.body is not None:
        job.body = payload.body
    if payload.publish_mode is not None:
        job.publish_mode = payload.publish_mode
    if payload.scheduled_at is not None or payload.publish_mode == "immediate":
        job.scheduled_at = to_shanghai_naive(payload.scheduled_at)
    _update_publish_options(job, payload)

    db.commit()
    db.refresh(job)
    return serialize_publish_job(job)


@router.post("/jobs/{job_id}/retry")
def retry_publish_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Publish job cannot be retried")

    job.status = "pending"
    job.publish_error = ""
    job.external_note_id = ""
    job.published_at = None
    _record_publish_control_task(db, current_user, job, "creator_publish_retry")
    db.commit()
    db.refresh(job)
    return serialize_publish_job(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_publish_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    if job.status not in {"pending", "scheduled"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Publish job cannot be cancelled")

    job.status = "cancelled"
    _record_publish_control_task(db, current_user, job, "creator_publish_cancel")
    db.commit()
    db.refresh(job)
    return serialize_publish_job(job)


@router.delete("/jobs/{job_id}")
def delete_publish_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    if job.status in {"publishing", "uploading"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="正在进行中的任务无法删除")

    db.execute(select(PublishAsset).where(PublishAsset.publish_job_id == job.id))
    for asset in db.scalars(select(PublishAsset).where(PublishAsset.publish_job_id == job.id)).all():
        db.delete(asset)
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.get("/jobs/{job_id}/assets")
def get_publish_assets(
    job_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    assets = db.scalars(
        select(PublishAsset).where(PublishAsset.publish_job_id == job.id).order_by(PublishAsset.id.asc())
    ).all()
    return paginated([serialize_publish_asset(asset) for asset in assets], page, page_size)


@router.post("/jobs/{job_id}/assets")
def create_publish_asset(
    job_id: int,
    payload: PublishAssetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    asset = PublishAsset(publish_job_id=job.id, asset_type=payload.asset_type, file_path=payload.file_path)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return serialize_publish_asset(asset)


@router.delete("/assets/{asset_id}")
def delete_publish_asset(
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    asset = _get_owned_publish_asset(db, current_user, asset_id)
    db.delete(asset)
    db.commit()
    return {"id": asset_id, "status": "deleted"}


@router.post("/assets/{asset_id}/upload")
def upload_publish_asset(
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_publish_adapter_factory),
):
    asset = _get_owned_publish_asset(db, current_user, asset_id)
    job = db.get(PublishJob, asset.publish_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish job not found")

    account = db.get(PlatformAccount, job.platform_account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if account.platform != "xhs" or account.sub_type not in {"creator", "pc"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Creator account required")

    cookies = _get_latest_account_cookies(db, account.id)
    asset.upload_status = "uploading"
    asset.upload_error = ""
    db.commit()

    try:
        payload = adapter_factory(cookies).upload_media(asset.file_path, asset.asset_type)
        asset.upload_status = "uploaded"
        asset.creator_media_id = extract_creator_media_id(payload)
        asset.creator_upload_info = json.dumps(payload, ensure_ascii=False)
        asset.upload_error = ""
        db.commit()
        db.refresh(asset)
        return serialize_publish_asset(asset)
    except Exception as exc:
        asset.upload_status = "failed"
        asset.upload_error = str(exc)
        db.commit()
        db.refresh(asset)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=asset.upload_error)


@router.post("/jobs/{job_id}/publish")
def publish_job_to_creator(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_publish_adapter_factory),
):
    """Publish one prepared job immediately.

    Intentionally **not** gated by ``require_risk_control``: this endpoint only
    runs when the signed-in user clicks "publish" in the publish center, and a
    click is the human confirmation itself. The risk switch guards the
    scheduler path (``auto_publish_enabled``), where nobody is watching.
    """
    job = _get_owned_publish_job(db, current_user, job_id)
    try:
        outcome = PublishService(db, current_user, adapter_factory).publish(
            job,
            task_type="creator_publish",
            # Manual scheduled publish hands ``postTime`` to Xiaohongshu and
            # keeps the job ``scheduled`` until the platform publishes it.
            platform_post_time=True,
            enforce_future_schedule=True,
            claim_before_media=False,
            # A validation/upload failure leaves the job pending so the author
            # can fix it in place. A failed post still marks the job failed.
            mark_failed_before_post=False,
        )
    except PublishNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except PublishConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except (PublishUploadError, PublishPlatformError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except PublishValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except PublishError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return serialize_publish_job(outcome.job)
