from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter
from backend.app.api.tasks import serialize_task
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.models import AccountCookieVersion, PlatformAccount, Task, User
from backend.app.services.analytics_snapshot_service import record_note_analytics
from backend.app.services.note_metrics_service import parse_published_at
from backend.app.services.publish_options_service import apply_publish_options, clean_topics

router = APIRouter(prefix="/xhs/creator", tags=["xhs-creator"])


class CreatorKeywordRequest(BaseModel):
    account_id: int
    keyword: str = Field(min_length=1, max_length=120)


class TopicRecommendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    limit: int = Field(default=8, ge=1, le=20)
    account_id: Optional[int] = None


class ImportPublishedRequest(BaseModel):
    account_id: int


class CreatorUploadRequest(BaseModel):
    account_id: int
    file_path: str = Field(min_length=1)
    media_type: Literal["image", "video"] = "image"


class CreatorImagePublishRequest(BaseModel):
    account_id: int
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="")
    image_file_infos: list[dict[str, Any]] = Field(min_length=1)
    publish_mode: Literal["immediate", "scheduled"] = "immediate"
    scheduled_at: Optional[datetime] = None
    topics: Optional[list[str]] = None
    location: Optional[str] = None
    privacy_type: Optional[int] = Field(default=None, ge=0, le=1)
    is_private: Optional[bool] = None


class CreatorVideoPublishRequest(BaseModel):
    account_id: int
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="")
    video_path: str = Field(default="", max_length=4000)
    video_info: dict[str, Any] = Field(default_factory=dict)
    publish_mode: Literal["immediate", "scheduled"] = "immediate"
    scheduled_at: Optional[datetime] = None
    topics: Optional[list[str]] = None
    location: Optional[str] = None
    privacy_type: Optional[int] = Field(default=None, ge=0, le=1)
    is_private: Optional[bool] = None


def get_creator_api_adapter_factory():
    return XhsCreatorApiAdapter


def _cookies_to_string(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return stripped
    if stripped.startswith("{"):
        cookies = json.loads(stripped)
        return "; ".join(f"{key}={cookie_value}" for key, cookie_value in cookies.items())
    return stripped


def _get_owned_creator_account(db: Session, current_user: User, account_id: int) -> PlatformAccount:
    account = db.get(PlatformAccount, account_id)
    if (
        account is None
        or account.user_id != current_user.id
        or account.platform != "xhs"
        # PC logins can drive the Creator APIs (shared session cookies), so both
        # account types are accepted here.
        or account.sub_type not in {"creator", "pc"}
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creator account not found")
    return account


def _get_latest_creator_cookies(db: Session, account: PlatformAccount) -> str:
    from backend.app.services.account_cookies import latest_cookies

    try:
        return latest_cookies(db, account, missing_detail="Creator account has no cookies")
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


def _adapter_for_account(
    db: Session,
    current_user: User,
    account_id: int,
    adapter_factory,
) -> tuple[PlatformAccount, Any]:
    account = _get_owned_creator_account(db, current_user, account_id)
    cookies = _get_latest_creator_cookies(db, account)
    return account, adapter_factory(cookies)


def _payload_items(raw_payload: Any) -> list[Any]:
    if isinstance(raw_payload, list):
        return raw_payload
    if not isinstance(raw_payload, dict):
        return []
    data = raw_payload.get("data") if isinstance(raw_payload.get("data"), dict) else raw_payload
    for key in ("items", "list", "notes", "topics", "pois"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _create_operation_task(
    db: Session,
    current_user: User,
    task_type: str,
    payload: dict[str, Any],
) -> Task:
    task = Task(
        user_id=current_user.id,
        platform="xhs",
        task_type=task_type,
        status="running",
        progress=20,
        payload=payload,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _complete_operation_task(db: Session, task: Task, payload: dict[str, Any]) -> Task:
    task.status = "completed"
    task.progress = 100
    task.payload = {**(task.payload or {}), **payload}
    db.commit()
    db.refresh(task)
    return task


def _fail_operation_task(db: Session, task: Task, error: str) -> None:
    task.status = "failed"
    task.progress = 100
    task.payload = {**(task.payload or {}), "error": error}
    db.commit()


def _scheduled_post_time(publish_mode: str, scheduled_at: Optional[datetime]) -> Optional[int]:
    if publish_mode != "scheduled":
        return None
    if scheduled_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scheduled publish time is required")
    return int(scheduled_at.timestamp() * 1000)


def _clean_topics(topics: Optional[list[str]]) -> list[str]:
    return clean_topics(topics)


def _apply_publish_options(note_info: dict[str, Any], payload: CreatorImagePublishRequest | CreatorVideoPublishRequest) -> None:
    options: dict[str, Any] = {"topics": payload.topics, "location": payload.location}
    if payload.is_private is not None:
        options["privacy_type"] = 1 if payload.is_private else 0
    elif payload.privacy_type is not None:
        options["privacy_type"] = payload.privacy_type
    apply_publish_options(note_info, options)


@router.post("/topics/search")
def search_topics(
    payload: CreatorKeywordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_api_adapter_factory),
):
    _, adapter = _adapter_for_account(db, current_user, payload.account_id, adapter_factory)
    success, message, raw_payload = adapter.get_topic(payload.keyword)
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "Creator topic search failed")
    return {"items": _payload_items(raw_payload), "raw": raw_payload}


def _collect_creator_topics(adapter: Any, keywords: list[str], per_keyword: int = 3) -> list[dict[str, Any]]:
    """Search the Creator topic library for the content's keywords."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for keyword in keywords[:4]:
        try:
            success, _message, raw = adapter.get_topic(keyword)
        except Exception:  # noqa: BLE001 - never fail the whole recommendation
            continue
        if not success or not isinstance(raw, dict):
            continue
        added_for_keyword = 0
        for item in (raw.get("data") or {}).get("topic_info_dtos") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            results.append(
                {
                    "title": name,
                    "topic_id": str(item.get("id") or ""),
                    "url": str(item.get("link") or ""),
                    "hot_text": "",
                    "hot_score": 0,
                    "score": 1.0,
                    "matched_terms": [str(keyword)],
                    "word_type": "",
                    "source": "creator_topic",
                }
            )
            added_for_keyword += 1
            if added_for_keyword >= per_keyword:
                break
        if len(results) >= per_keyword * 4:
            break
    return results


@router.post("/topic-recommendations")
def recommend_content_topics(
    payload: TopicRecommendRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_api_adapter_factory),
):
    """按内容匹配话题：创作者话题库 + 小红书热搜（均不消耗 RedFox 额度）。

    返回的话题名可直接写入发布任务 ``topics``，发布时会自动解析成话题 ID。
    """
    from backend.app.services.hot_topic_trend_service import attach_trends
    from backend.app.services.topic_recommendation_service import recommend_topics

    success, message, data = recommend_topics(payload.content, limit=payload.limit)
    if not success:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=message or "话题推荐暂不可用")

    # Optionally enrich with the Creator topic library (better for publishing,
    # because those names resolve to real topic IDs).
    if payload.account_id and data.get("hashtags"):
        try:
            account = _get_owned_creator_account(db, current_user, payload.account_id)
            adapter = adapter_factory(_get_latest_creator_cookies(db, account))
            creator_items = _collect_creator_topics(adapter, list(data["hashtags"]))
            if creator_items:
                existing = {item["title"] for item in creator_items}
                merged = creator_items + [
                    item for item in data.get("items", []) if item["title"] not in existing
                ]
                data["items"] = merged[: payload.limit]
                data["creator_topic_count"] = len(creator_items)
        except HTTPException:
            pass
        except Exception:  # noqa: BLE001 - enrichment is best-effort
            pass

    attach_trends(db, data.get("items", []))
    return data


@router.post("/locations/search")
def search_locations(
    payload: CreatorKeywordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_api_adapter_factory),
):
    _, adapter = _adapter_for_account(db, current_user, payload.account_id, adapter_factory)
    success, message, raw_payload = adapter.get_location_info(payload.keyword)
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "Creator location search failed")
    return {"items": _payload_items(raw_payload), "raw": raw_payload}


@router.post("/assets/upload")
def upload_asset(
    payload: CreatorUploadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_api_adapter_factory),
):
    account, adapter = _adapter_for_account(db, current_user, payload.account_id, adapter_factory)
    task = _create_operation_task(
        db,
        current_user,
        "creator_direct_upload",
        {"account_id": account.id, "file_path": payload.file_path, "media_type": payload.media_type},
    )
    try:
        upload_payload = adapter.upload_media(payload.file_path, payload.media_type)
        task = _complete_operation_task(db, task, {"payload": upload_payload})
        return {"task": serialize_task(task), "payload": upload_payload}
    except Exception as exc:
        _fail_operation_task(db, task, str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/publish/image")
def publish_image(
    payload: CreatorImagePublishRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_api_adapter_factory),
):
    account, adapter = _adapter_for_account(db, current_user, payload.account_id, adapter_factory)
    note_info = {
        "title": payload.title,
        "desc": payload.body,
        "media_type": "image",
        "image_file_infos": payload.image_file_infos,
        "type": 1,
        "postTime": _scheduled_post_time(payload.publish_mode, payload.scheduled_at),
    }
    _apply_publish_options(note_info, payload)
    task = _create_operation_task(
        db,
        current_user,
        "creator_direct_publish",
        {"account_id": account.id, "media_type": "image", "publish_mode": payload.publish_mode},
    )
    try:
        publish_payload = adapter.post_note(note_info)
        task = _complete_operation_task(db, task, {"payload": publish_payload})
        return {"task": serialize_task(task), "payload": publish_payload}
    except Exception as exc:
        _fail_operation_task(db, task, str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/publish/video")
def publish_video(
    payload: CreatorVideoPublishRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_api_adapter_factory),
):
    account, adapter = _adapter_for_account(db, current_user, payload.account_id, adapter_factory)
    video_source = payload.video_path.strip()
    if not video_source and isinstance(payload.video_info.get("video"), str):
        video_source = payload.video_info["video"]
    if not video_source:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="video_path 不能为空（本地路径或 /api/files/media 地址）",
        )
    try:
        video_bytes = adapter.resolve_media_bytes(video_source)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"视频素材读取失败: {exc}",
        ) from exc
    note_info = {
        "title": payload.title,
        "desc": payload.body,
        "media_type": "video",
        "video": video_bytes,
        "type": 1,
        "postTime": _scheduled_post_time(payload.publish_mode, payload.scheduled_at),
    }
    _apply_publish_options(note_info, payload)
    task = _create_operation_task(
        db,
        current_user,
        "creator_direct_publish",
        {"account_id": account.id, "media_type": "video", "publish_mode": payload.publish_mode},
    )
    try:
        publish_payload = adapter.post_note(note_info)
        task = _complete_operation_task(db, task, {"payload": publish_payload})
        return {"task": serialize_task(task), "payload": publish_payload}
    except Exception as exc:
        _fail_operation_task(db, task, str(exc))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.get("/published")
def published(
    account_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_api_adapter_factory),
):
    _, adapter = _adapter_for_account(db, current_user, account_id, adapter_factory)
    success, message, raw_payload = adapter.get_published_notes()
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "Creator published list failed")
    return {"items": _payload_items(raw_payload), "raw": raw_payload}


@router.post("/published/import")
def import_published_to_library(
    payload: ImportPublishedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_api_adapter_factory),
):
    """把创作者中心的已发布笔记写入「内容库」，供数据洞察/爆款分析使用。

    只做本地入库（不额外请求小红书详情页），重复导入会更新同一条笔记。
    """
    from backend.app.core.time import shanghai_now
    from backend.app.models import Note
    from backend.app.services.note_metrics_service import compute_note_metrics

    account, adapter = _adapter_for_account(db, current_user, payload.account_id, adapter_factory)
    success, message, raw_payload = adapter.get_published_notes()
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "Creator published list failed")

    items = _payload_items(raw_payload)
    if not items:
        return {"imported": 0, "updated": 0, "total": 0}

    followers = 0
    try:
        import json as _json

        profile = _json.loads(account.profile_json or "{}")
        followers = int(profile.get("followers") or 0)
    except Exception:  # noqa: BLE001
        followers = 0

    imported = updated = 0
    now = shanghai_now()
    changed_notes = []
    for item in items:
        if not isinstance(item, dict):
            continue
        note_id = str(item.get("id") or "").strip()
        if not note_id:
            continue
        likes = int(item.get("likes") or 0)
        collects = int(item.get("collected_count") or 0)
        comments = int(item.get("comments_count") or 0)
        shares = int(item.get("shared_count") or 0)
        rates = compute_note_metrics(likes, collects, comments, shares, followers)

        note = db.scalars(
            select(Note).where(Note.user_id == current_user.id, Note.note_id == note_id)
        ).first()
        if note is None:
            note = Note(
                user_id=current_user.id,
                platform_account_id=account.id,
                platform="xhs",
                note_id=note_id,
                source_type="creator",
            )
            db.add(note)
            imported += 1
        else:
            if note.source_type != "publish":
                note.source_type = "creator"
            updated += 1

        note.title = str(item.get("display_title") or note.title or "")
        note.author_name = account.nickname or note.author_name or ""
        note.author_id = account.external_user_id or note.author_id or ""
        note.author_fans = followers or note.author_fans or 0
        note.like_count = likes
        note.collect_count = collects
        note.comment_count = comments
        note.share_count = shares
        note.like_fan_ratio = rates["like_fan_ratio"]
        note.engagement_rate = rates["engagement_rate"]
        note.metrics_fetched_at = now
        # 发布时间必须落到列上，不能只放 raw_json。
        #
        # 列表接口、`published_within_days`、低粉窗口都只读 `note.published_at`
        # （notes.py:229/836/845），raw 里的 ``time`` 没人读。只写 raw 的话，
        # 导入的笔记在「发布」列显示「—」，按时间筛也会被整批漏掉。
        # 只在 NULL 时写：重复导入不覆盖已经解析出来的时间。
        if note.published_at is None:
            published = parse_published_at(item.get("time"))
            if published is not None:
                note.published_at = published
        note.raw_json = {
            "source": "creator_published",
            "time": item.get("time"),
            "view_count": item.get("view_count"),
            "images_list": item.get("images_list"),
            "xsec_token": item.get("xsec_token"),
            "xsec_source": item.get("xsec_source"),
        }
        changed_notes.append(note)

    db.flush()
    for note in changed_notes:
        record_note_analytics(db, note, source="creator_center")
    db.commit()
    return {"imported": imported, "updated": updated, "total": imported + updated}
