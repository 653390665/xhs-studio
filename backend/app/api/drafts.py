from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now, to_shanghai_naive
from backend.app.models import AiDraft, AiGeneratedAsset, DraftAsset, DraftChatMessage, DraftVersion, Note, NoteAsset, PlatformAccount, PublishAsset, PublishJob, User
from backend.app.schemas.common import paginated
from backend.app.schemas.serializers import serialize_draft, serialize_publish_job
from backend.app.services.agent_service import _build_visual_brief
from backend.app.services.publish_preflight_service import preflight_draft, preflight_publish_job
from backend.app.services.publish_options_service import clean_topics
from backend.app.services.skill_library_service import active_creation_skill_version

router = APIRouter(prefix="/drafts", tags=["drafts"])


class DraftCreateRequest(BaseModel):
    platform: str = Field(pattern="^xhs$")
    source_note_id: Optional[int] = None
    platform_account_id: Optional[int] = None
    title: str = ""
    body: str = ""
    intent: str = Field(default="publish", max_length=32)


class DraftUpdateRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    # Two shapes exist in the database: plain names and {id, name} objects.
    # The schema used to accept only dicts, which made the 20 drafts holding
    # strings impossible to correct through the API.
    tags: Optional[list[Union[str, dict]]] = None
    platform_account_id: Optional[int] = None
    pillar: Optional[str] = Field(default=None, max_length=64)
    experiment: Optional[str] = Field(default=None, max_length=64)
    # 这篇按哪个结构模板写。生成时能带，但老草稿和手写的稿子没有——
    # 没有这个字段，`/drafts/{id}/preflight` 里的结构检查永远不会触发，
    # 「选了模板」和「没选」在自检里完全一样。
    template_id: Optional[int] = None


class DraftSendToPublishRequest(BaseModel):
    platform_account_id: Optional[int] = None
    publish_mode: str = Field(default="immediate", pattern="^(immediate|scheduled)$")
    scheduled_at: Optional[datetime] = None
    topics: Optional[list[str]] = None
    location: Optional[str] = None
    privacy_type: Optional[int] = Field(default=None, ge=0, le=1)
    is_private: Optional[bool] = None


class DraftBatchScheduleRequest(BaseModel):
    draft_ids: list[int] = Field(min_length=1, max_length=30)
    platform_account_id: int
    start_at: datetime
    interval_days: int = Field(default=1, ge=0, le=30)
    topics: Optional[list[str]] = None


def _clean_topics(topics: Optional[list[str]]) -> list[str]:
    return clean_topics(topics)


def _build_publish_options(payload: DraftSendToPublishRequest) -> dict[str, Any]:
    options: dict[str, Any] = {}
    topics = _clean_topics(payload.topics)
    if topics:
        options["topics"] = topics
    if payload.location and payload.location.strip():
        options["location"] = payload.location.strip()
    if payload.is_private is not None:
        options["is_private"] = payload.is_private
        options["privacy_type"] = 1 if payload.is_private else 0
    elif payload.privacy_type is not None:
        options["privacy_type"] = payload.privacy_type
        options["is_private"] = payload.privacy_type == 1
    return options


def _snapshot_draft(db: Session, draft: AiDraft, user_id: int, source: str) -> None:
    latest = db.scalars(
        select(DraftVersion)
        .where(DraftVersion.draft_id == draft.id)
        .order_by(DraftVersion.version_no.desc())
    ).first()
    db.add(
        DraftVersion(
            user_id=user_id,
            draft_id=draft.id,
            version_no=(latest.version_no + 1) if latest else 1,
            title=draft.title or "",
            body=draft.body or "",
            tags=draft.tags or [],
            source=source,
            skill_version=draft.skill_version or "",
        )
    )
    db.flush()


def _draft_asset_counts(db: Session, draft_ids: list[int]) -> dict[int, dict[str, int]]:
    """One grouped query for the draft list's readiness badges (no N+1)."""
    if not draft_ids:
        return {}
    rows = db.execute(
        select(
            DraftAsset.draft_id,
            DraftAsset.asset_type,
            func.count(DraftAsset.id),
        )
        .where(DraftAsset.draft_id.in_(draft_ids))
        .group_by(DraftAsset.draft_id, DraftAsset.asset_type)
    ).all()
    counts: dict[int, dict[str, int]] = {}
    for draft_id, asset_type, count in rows:
        bucket = counts.setdefault(draft_id, {"image": 0, "video": 0})
        if asset_type in bucket:
            bucket[asset_type] = int(count)
    return counts


def _serialize_draft(draft: AiDraft) -> dict:
    """Kept as a local alias so every call site in this file stays unchanged.

    The implementation lives in ``schemas/serializers.py``: three routers each
    had a copy and the one in ``notes.py`` had drifted down to 6 fields.
    """
    return serialize_draft(draft)


def _get_owned_account(db: Session, current_user: User, account_id: int) -> PlatformAccount:
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform account not found")
    return account


def _serialize_publish_job(job: PublishJob) -> dict:
    """Same payload as ``api/publish.py`` — see ``schemas/serializers.py``.

    The partial version here was missing ``publish_error`` among 6 other keys.
    """
    return serialize_publish_job(job)


def _get_owned_source_note(db: Session, current_user: User, note_id: int) -> Note:
    note = db.get(Note, note_id)
    if note is None or note.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source note not found")
    return note


@router.get("")
def get_drafts(
    platform: Optional[str] = None,
    review_status: Optional[Literal["all", "pending", "adopted", "discarded"]] = None,
    origin: Optional[str] = None,
    account_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(AiDraft).where(AiDraft.user_id == current_user.id)
    if platform:
        statement = statement.where(AiDraft.platform == platform)
    if review_status and review_status != "all":
        statement = statement.where(AiDraft.review_status == review_status)
    if origin and origin != "all":
        statement = statement.where(AiDraft.origin == origin)
    # The writing page shows one account's drafts at a time; without this filter
    # the left column mixed several accounts and "which account is this for"
    # could only be answered by opening each one.
    if account_id is not None:
        statement = statement.where(AiDraft.platform_account_id == account_id)
    drafts = db.scalars(statement.order_by(AiDraft.created_at.desc())).all()
    counts = _draft_asset_counts(db, [draft.id for draft in drafts])
    items = []
    for draft in drafts:
        item = _serialize_draft(draft)
        bucket = counts.get(draft.id, {})
        image_count = bucket.get("image", 0)
        video_count = bucket.get("video", 0)
        item.update(
            asset_count=image_count + video_count,
            image_count=image_count,
            video_count=video_count,
            media_ready=bool(image_count or video_count),
            account_ready=bool(draft.platform_account_id),
        )
        items.append(item)
    return paginated(items, page, page_size)


@router.post("")
def create_draft(
    payload: DraftCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source_note = None
    if payload.source_note_id is not None:
        source_note = _get_owned_source_note(db, current_user, payload.source_note_id)
    if payload.platform_account_id is not None:
        _get_owned_account(db, current_user, payload.platform_account_id)

    # Extract tags from source note
    tags = None
    if source_note and source_note.raw_json:
        raw = source_note.raw_json if isinstance(source_note.raw_json, dict) else {}
        tag_list = raw.get("tags") or raw.get("tag_list")
        if not tag_list:
            data = raw.get("data")
            if isinstance(data, dict):
                items = data.get("items") or []
                if items and isinstance(items[0], dict):
                    card = items[0].get("note_card") or {}
                    if isinstance(card, dict):
                        tag_list = card.get("tag_list")
        if isinstance(tag_list, list):
            tags = []
            for t in tag_list:
                if isinstance(t, str):
                    tags.append({"name": t})
                elif isinstance(t, dict) and t.get("name"):
                    tags.append({"id": str(t.get("id", "")), "name": str(t["name"])})

    draft = AiDraft(
        user_id=current_user.id,
        platform=payload.platform,
        platform_account_id=payload.platform_account_id,
        title=payload.title or (source_note.title if source_note else ""),
        body=payload.body or (source_note.content if source_note else ""),
        tags=tags,
        source_note_id=source_note.id if source_note else None,
        origin="manual",
        skill_version=active_creation_skill_version(
            db, current_user.id, payload.platform_account_id
        ),
    )
    db.add(draft)
    db.flush()

    if source_note:
        source_assets = db.scalars(
            select(NoteAsset).where(NoteAsset.note_id == source_note.id).order_by(NoteAsset.sort_order.asc(), NoteAsset.id.asc())
        ).all()
        for idx, na in enumerate(source_assets):
            db.add(DraftAsset(
                draft_id=draft.id,
                asset_type=na.asset_type,
                url=na.url,
                local_path=na.local_path,
                sort_order=idx,
            ))

    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft)


def _create_publish_job_from_draft(
    db: Session,
    current_user: User,
    draft: AiDraft,
    payload: DraftSendToPublishRequest,
) -> PublishJob:
    account_id: Optional[int] = None
    if payload.platform_account_id is not None:
        account = db.get(PlatformAccount, payload.platform_account_id)
        if account is None or account.user_id != current_user.id or account.platform != draft.platform:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform account not found")
        account_id = account.id

    options = _build_publish_options(payload)
    if draft.tags:
        options["draft_tags"] = draft.tags

    job = PublishJob(
        user_id=current_user.id,
        platform_account_id=account_id,
        source_draft_id=draft.id,
        platform=draft.platform,
        title=draft.title,
        body=draft.body,
        publish_mode=payload.publish_mode,
        publish_options=json.dumps(options, ensure_ascii=False, separators=(",", ":")),
        origin=draft.origin or "manual",
        skill_version=draft.skill_version or "",
        pillar=draft.pillar or "",
        experiment=draft.experiment or "",
        scheduled_at=to_shanghai_naive(payload.scheduled_at),
        status="pending",
    )
    db.add(job)
    db.flush()

    draft_assets = db.scalars(
        select(DraftAsset).where(DraftAsset.draft_id == draft.id).order_by(DraftAsset.sort_order.asc(), DraftAsset.id.asc())
    ).all()
    for da in draft_assets:
        if da.local_path:
            file_path = f"/api/files/media/{da.local_path}"
        else:
            file_path = da.url
        db.add(
            PublishAsset(
                publish_job_id=job.id,
                asset_type=da.asset_type,
                file_path=file_path,
                upload_status="pending",
            )
        )
    db.flush()
    return job


def _find_active_publish_job_for_draft(
    db: Session,
    user_id: int,
    draft_id: int,
) -> PublishJob | None:
    """同一条草稿是否已经有一条「还会被发出去」的任务。

    ``published`` 不算：它已经发完了。把它算进来的后果是——
    用户改完稿再点送发布，拿回的是那条已发布的旧 job（标题还是上一版），
    界面提示「已送进队列」，实际什么都没变，新内容永远发不出去。
    """
    return db.scalars(
        select(PublishJob)
        .where(
            PublishJob.user_id == user_id,
            PublishJob.source_draft_id == draft_id,
            PublishJob.status.in_(["pending", "scheduled", "publishing"]),
        )
        .order_by(PublishJob.id.desc())
    ).first()


@router.post("/{draft_id}/send-to-publish")
def send_draft_to_publish(
    draft_id: int,
    payload: DraftSendToPublishRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    # 账号必填：没有账号的任务进队列后点确认才报错，用户会以为已经排好了。
    if payload.platform_account_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先选择发布账号，再送进发布队列",
        )

    existing = _find_active_publish_job_for_draft(db, current_user.id, draft.id)
    if existing is not None:
        # 已有待发任务时复用是幂等的，但只有在内容/账号/时间都没变时才对。
        # 变了还复用，等于让用户以为改后的稿子已经排进去了。
        same_account = existing.platform_account_id == payload.platform_account_id
        same_mode = existing.publish_mode == payload.publish_mode
        same_time = (
            to_shanghai_naive(payload.scheduled_at) == existing.scheduled_at
            if payload.publish_mode == "scheduled"
            else True
        )
        same_content = (existing.title or "") == (draft.title or "") and (
            existing.body or ""
        ) == (draft.body or "")
        if same_account and same_mode and same_time and same_content:
            return _serialize_publish_job(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "这篇稿子已经有一条待发任务，但账号、时间或内容已经变了。"
                "请先到「发布」里取消那条旧任务，再重新送一次。"
            ),
        )

    job = _create_publish_job_from_draft(db, current_user, draft, payload)
    # 送发布之后草稿就属于这个账号了。
    #
    # 不回写的话，草稿永远 ``platform_account_id=NULL``：写稿页的「这个账号的 +
    # 未分配的」规则会让它在每个账号视图里都出现，而生成标题/自检读的是草稿
    # 上的账号、送发布读的是页面选的账号——同一篇稿三个地方用三个身份。
    if draft.platform_account_id is None:
        draft.platform_account_id = payload.platform_account_id
    # 送进队列时跑一遍预检，但**只拦内容类错误**。
    #
    # 以前只有 scheduled 才查，于是空标题/空正文的草稿能直接进队列
    # （status=pending），点确认时才 400，而那条 job 既没有 publish_error
    # 也不能重试——用户唯一的出路是「取消」。
    #
    # 素材类错误不在这里拦（``asset*`` 全部放行）：队列支持后补素材
    # （`POST /publish/jobs/{id}/assets`），先排队再配图是正常流程；
    # 而且「本地文件是否存在」取决于运行时的 storage_dir，换台机器就会
    # 全部误报。真正的硬校验在发布那一刻由 ``publish_service`` 做。
    preflight = preflight_publish_job(db, current_user, job)
    blocking = [
        item
        for item in preflight["errors"]
        if not item["key"].startswith("asset")
    ]
    if blocking:
        db.rollback()
        messages = "；".join(item["message"] for item in blocking)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"发布前检查未通过：{messages}",
        )
    db.commit()
    db.refresh(job)
    return _serialize_publish_job(job)


@router.post("/batch-send-to-publish")
def batch_send_drafts_to_publish(
    payload: DraftBatchScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_at = to_shanghai_naive(payload.start_at)
    if start_at is None or start_at <= shanghai_now():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="开始时间必须晚于当前时间")

    items: list[dict[str, Any]] = []
    created = 0
    for index, draft_id in enumerate(payload.draft_ids):
        draft = db.get(AiDraft, draft_id)
        if draft is None or draft.user_id != current_user.id:
            items.append({"draft_id": draft_id, "status": "failed", "error": "草稿不存在或无权限"})
            continue
        try:
            scheduled_at = start_at + timedelta(days=payload.interval_days * index)
            job = _create_publish_job_from_draft(
                db,
                current_user,
                draft,
                DraftSendToPublishRequest(
                    platform_account_id=payload.platform_account_id,
                    publish_mode="scheduled",
                    scheduled_at=scheduled_at,
                    topics=payload.topics,
                ),
            )
            preflight = preflight_publish_job(db, current_user, job)
            if not preflight["ok"]:
                db.rollback()
                errors = "；".join(item["message"] for item in preflight["errors"])
                items.append(
                    {
                        "draft_id": draft_id,
                        "status": "failed",
                        "error": errors,
                        "checks": preflight["checks"],
                    }
                )
                continue
            db.commit()
            db.refresh(job)
            created += 1
            items.append(
                {
                    "draft_id": draft_id,
                    "status": "ok",
                    "job_id": job.id,
                    "scheduled_at": scheduled_at.isoformat(),
                    "warnings": preflight["warnings"],
                }
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            items.append({"draft_id": draft_id, "status": "failed", "error": str(exc)[:300]})
    return {"created_count": created, "failed_count": len(items) - created, "items": items}


class DraftReviewRequest(BaseModel):
    review_status: Literal["pending", "adopted", "discarded"]


class DraftVisualBriefRequest(BaseModel):
    style: str = Field(default="", max_length=32)


@router.get("/{draft_id}/preflight")
def get_draft_preflight(
    draft_id: int,
    account_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return preflight_draft(db, current_user, draft, account_id=account_id)


@router.post("/{draft_id}/visual-brief")
def build_draft_visual_brief(
    draft_id: int,
    payload: DraftVisualBriefRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    try:
        return _build_visual_brief(
            db,
            current_user,
            {"draft_id": draft.id, "style": payload.style.strip()},
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{draft_id}")
def get_draft(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One draft, by id.

    The list endpoint caps ``page_size`` at 100 and the writing page needs to
    open a draft that may be older than that; fetching the whole list and
    filtering in the browser was the workaround, and it silently failed once a
    user had more than 100 drafts.
    """
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    item = _serialize_draft(draft)
    counts = _draft_asset_counts(db, [draft.id]).get(draft.id, {})
    image_count = counts.get("image", 0)
    video_count = counts.get("video", 0)
    item.update(
        asset_count=image_count + video_count,
        image_count=image_count,
        video_count=video_count,
        media_ready=bool(image_count or video_count),
        account_ready=bool(draft.platform_account_id),
    )
    return item


@router.patch("/{draft_id}/review")
def review_draft(
    draft_id: int,
    payload: DraftReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    draft.review_status = payload.review_status
    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft)


@router.patch("/{draft_id}")
def update_draft(
    draft_id: int,
    payload: DraftUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")

    if payload.title is not None or payload.body is not None or payload.tags is not None:
        _snapshot_draft(db, draft, current_user.id, "manual")

    if payload.pillar is not None:
        draft.pillar = payload.pillar
    if payload.experiment is not None:
        draft.experiment = payload.experiment
    if payload.template_id is not None:
        # 0 表示「取消关联」，其它值必须是自己的模板
        if payload.template_id == 0:
            draft.template_id = None
        else:
            from backend.app.models import ViralTemplate

            template = db.get(ViralTemplate, payload.template_id)
            if template is None or template.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="结构模板不存在"
                )
            draft.template_id = payload.template_id

    if payload.title is not None:
        draft.title = payload.title
    if payload.body is not None:
        draft.body = payload.body
    if payload.tags is not None:
        draft.tags = list(payload.tags)
        flag_modified(draft, "tags")
    if payload.platform_account_id is not None:
        _get_owned_account(db, current_user, payload.platform_account_id)
        draft.platform_account_id = payload.platform_account_id

    db.commit()
    db.refresh(draft)
    return _serialize_draft(draft)


@router.delete("/{draft_id}")
def delete_draft(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    # Keep generated images and publish history: detach the draft instead of
    # deleting rows the user still sees elsewhere.
    db.execute(
        update(AiGeneratedAsset)
        .where(AiGeneratedAsset.draft_id == draft.id)
        .values(draft_id=None)
    )
    # 未完成的任务必须取消，不能只断开关联就留着。
    # 只把 ``source_draft_id`` 置 NULL 的话，队列里会剩一条 pending：
    # 追溯不到来源、也改不了稿，而「待确认」的计数继续算它。
    db.execute(
        update(PublishJob)
        .where(
            PublishJob.source_draft_id == draft.id,
            PublishJob.status.in_(("pending", "scheduled")),
        )
        .values(status="cancelled", publish_error="来源草稿已删除")
    )
    # 已发布/失败的历史保留，仅断开指向（草稿没了，但那条记录仍有意义）。
    db.execute(
        update(PublishJob)
        .where(PublishJob.source_draft_id == draft.id)
        .values(source_draft_id=None)
    )
    db.execute(delete(DraftAsset).where(DraftAsset.draft_id == draft.id))
    db.execute(delete(DraftChatMessage).where(DraftChatMessage.draft_id == draft.id))
    db.execute(delete(DraftVersion).where(DraftVersion.draft_id == draft.id))
    db.delete(draft)
    db.commit()
    return {"id": draft_id, "status": "deleted"}


# ---------------------------------------------------------------------------
# Draft assets
# ---------------------------------------------------------------------------

def _serialize_draft_asset(asset: DraftAsset) -> dict:
    display_url = f"/api/files/media/{asset.local_path}" if asset.local_path else asset.url
    return {
        "id": asset.id,
        "draft_id": asset.draft_id,
        "asset_type": asset.asset_type,
        "url": display_url,
        "local_path": asset.local_path,
        "sort_order": asset.sort_order,
    }


class DraftAssetCreateRequest(BaseModel):
    asset_type: str = Field(pattern="^(image|video)$")
    url: str = Field(default="", max_length=2048)
    local_path: str = Field(default="", max_length=512)


class DraftAssetReorderRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1)


@router.get("/{draft_id}/assets")
def get_draft_assets(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    assets = db.scalars(
        select(DraftAsset).where(DraftAsset.draft_id == draft.id).order_by(DraftAsset.sort_order.asc(), DraftAsset.id.asc())
    ).all()
    return {"items": [_serialize_draft_asset(a) for a in assets]}


@router.post("/{draft_id}/assets")
def add_draft_asset(
    draft_id: int,
    payload: DraftAssetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    max_order = db.scalar(select(func.max(DraftAsset.sort_order)).where(DraftAsset.draft_id == draft.id)) or 0
    asset = DraftAsset(
        draft_id=draft.id,
        asset_type=payload.asset_type,
        url=payload.url,
        local_path=payload.local_path,
        sort_order=max_order + 1,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize_draft_asset(asset)


@router.delete("/{draft_id}/assets/{asset_id}")
def delete_draft_asset(
    draft_id: int,
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    asset = db.scalars(select(DraftAsset).where(DraftAsset.id == asset_id, DraftAsset.draft_id == draft.id)).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    db.delete(asset)
    db.commit()
    return {"id": asset_id, "status": "deleted"}


class DraftAssetUpdateRequest(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2048)
    local_path: Optional[str] = Field(default=None, max_length=512)


@router.patch("/{draft_id}/assets/{asset_id}")
def update_draft_asset(
    draft_id: int,
    asset_id: int,
    payload: DraftAssetUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    asset = db.scalars(select(DraftAsset).where(DraftAsset.id == asset_id, DraftAsset.draft_id == draft.id)).first()
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if payload.url is not None:
        asset.url = payload.url
    if payload.local_path is not None:
        asset.local_path = payload.local_path
    db.commit()
    db.refresh(asset)
    return _serialize_draft_asset(asset)


@router.put("/{draft_id}/assets/reorder")
def reorder_draft_assets(
    draft_id: int,
    payload: DraftAssetReorderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = db.get(AiDraft, draft_id)
    if draft is None or draft.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    assets = db.scalars(select(DraftAsset).where(DraftAsset.draft_id == draft.id)).all()
    asset_map = {a.id: a for a in assets}
    for idx, aid in enumerate(payload.asset_ids):
        if aid in asset_map:
            asset_map[aid].sort_order = idx
    db.commit()
    return {"ok": True}
