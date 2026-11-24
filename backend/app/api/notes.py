from __future__ import annotations

import csv
import io
import json
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from backend.app.api.platforms.xhs.pc import (
    _cookies_to_string,
    get_xhs_pc_api_adapter_factory,
    normalize_comment_payload,
)
from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.core.security import decrypt_text
from backend.app.models import AccountCookieVersion, AiDraft, Note, NoteAsset, NoteComment, PlatformAccount, Tag, User, note_tags
from backend.app.schemas.common import paginated
from backend.app.schemas.serializers import serialize_draft
from backend.app.services.analytics_snapshot_service import record_note_analytics
from backend.app.services.note_metrics_service import compute_note_metrics, extract_note_metrics, normalize_author_profile, parse_published_at
from backend.app.services.note_metrics_refresh_service import refresh_one_note
from backend.app.services.publish_preflight_service import preflight_draft
from backend.app.api.ai import _load_creation_skill_text, _text_model_context, get_text_ai_client
from backend.app.services.ai_service import TextAiClient, parse_generated_note
from backend.app.services.risk_control_service import require_risk_control
from backend.app.services.skill_library_service import active_creation_skill_version, module_skill_text

router = APIRouter(prefix="/notes", tags=["notes"])


class BatchSaveNoteItem(BaseModel):
    note_id: str = Field(min_length=1, max_length=128)
    note_url: str = ""
    title: str = ""
    content: str = ""
    author_name: str = ""
    author_id: str = ""
    author_fans: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    collects: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    like_fan_ratio: float = Field(default=0.0, ge=0)
    engagement_rate: float = Field(default=0.0, ge=0)
    cover_url: str = ""
    video_url: str = ""
    video_addr: str = ""
    image_urls: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class BatchSaveNotesRequest(BaseModel):
    account_id: int
    fetch_comments: bool = False
    notes: list[BatchSaveNoteItem] = Field(min_length=1)


class BatchTagNotesRequest(BaseModel):
    note_ids: list[int] = Field(min_length=1)
    tag_ids: list[int] = Field(default_factory=list)
    mode: Literal["replace", "add", "remove"] = "replace"


class BatchCreateDraftsRequest(BaseModel):
    note_ids: list[int] = Field(min_length=1)
    intent: str = Field(default="rewrite", max_length=32)


class ExportNotesRequest(BaseModel):
    note_ids: list[int] = Field(min_length=1)
    format: Literal["json", "csv"] = "json"


def _serialize_tag(tag: Tag) -> dict:
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
    }


def _get_note_tags(db: Session, note_id: int) -> list[dict]:
    tags = db.scalars(
        select(Tag)
        .join(note_tags, Tag.id == note_tags.c.tag_id)
        .where(note_tags.c.note_id == note_id)
        .order_by(Tag.id.asc())
    ).all()
    return [_serialize_tag(tag) for tag in tags]


def _get_note_assets(db: Session, note: Note) -> list[NoteAsset]:
    return db.scalars(select(NoteAsset).where(NoteAsset.note_id == note.id).order_by(NoteAsset.sort_order.asc(), NoteAsset.id.asc())).all()


def _asset_display_url(asset: NoteAsset) -> str:
    """本地副本优先，但本地文件真的在才算。

    只判 ``local_path`` 非空、不判文件存在，会把整站封面变成 404：
    换台机器、或者只拷了 DB 没拷 ``storage/media``，前端拿到的
    ``/api/files/media/...`` 全是坏的，而同一行的 ``asset.url`` 里明明存着
    可用的 CDN 地址。这里加一次 ``is_file()``，缺文件就回落 CDN。
    """
    if asset.local_path:
        from backend.app.core.config import get_settings

        local = Path(get_settings().storage_dir) / "media" / asset.local_path
        if local.is_file():
            return f"/api/files/media/{asset.local_path}"
        # 文件不在：回落 CDN（有就用），否则仍返回本地路径让 404 显式暴露。
        return asset.url or f"/api/files/media/{asset.local_path}"
    return asset.url


def _cover_from_container(container: Any) -> str:
    if not isinstance(container, dict):
        return ""
    candidates: list[Any] = [
        container.get("cover_url"),
        container.get("image_url"),
        container.get("cover"),
    ]
    # ``images_list`` 是抖音/外部导入语料的写法（下划线 + 复数），
    # ``image_list`` 是小红书搜索/详情 payload 的写法。少认一个，那一批
    # 笔记的封面就永远是空的，而且界面上看不出来是「没有图」还是「没认出来」。
    for key in ("image_list", "images_list", "images", "imageList"):
        value = container.get(key)
        if isinstance(value, list):
            candidates.extend(value[:3])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.startswith("http"):
            return candidate
        if isinstance(candidate, dict):
            for key in ("url_default", "url_pre", "url", "master_url"):
                value = candidate.get(key)
                if isinstance(value, str) and value.startswith("http"):
                    return value
            info_list = candidate.get("info_list")
            if isinstance(info_list, list):
                for info in info_list:
                    if isinstance(info, dict):
                        value = info.get("url")
                        if isinstance(value, str) and value.startswith("http"):
                            return value
        if isinstance(candidate, list):
            for item in candidate[:3]:
                if isinstance(item, str) and item.startswith("http"):
                    return item
                if isinstance(item, dict):
                    for key in ("url_default", "url_pre", "url", "master_url"):
                        value = item.get(key)
                        if isinstance(value, str) and value.startswith("http"):
                            return value
    return ""


def _raw_cover_url(raw: dict[str, Any]) -> str:
    """Extract a cover URL from search/detail payloads without downloading it."""
    containers: list[Any] = [raw, raw.get("note_card"), raw.get("note")]
    data = raw.get("data")
    if isinstance(data, dict):
        containers.extend([data, data.get("note_card"), data.get("note")])
        items = data.get("items")
        if isinstance(items, list):
            for item in items[:1]:
                if isinstance(item, dict):
                    containers.extend([item, item.get("note_card"), item.get("note")])
    # 详情接口和搜索接口的 items 位置不同：搜索在 data.items，详情在顶层
    # items。只读 data.items 会让详情采集的那批笔记拿不到封面。
    top_items = raw.get("items")
    if isinstance(top_items, list):
        for item in top_items[:1]:
            if isinstance(item, dict):
                containers.extend([item, item.get("note_card"), item.get("note")])
    for container in containers:
        cover = _cover_from_container(container)
        if cover:
            return cover
    return ""


def _serialize_note(db: Session, note: Note, *, brief: bool = False) -> dict:
    assets = _get_note_assets(db, note)
    image_assets = [asset for asset in assets if asset.asset_type == "image"]
    video_assets = [asset for asset in assets if asset.asset_type == "video"]
    asset_urls = [_asset_display_url(asset) for asset in assets if asset.url or asset.local_path]
    raw = note.raw_json if isinstance(note.raw_json, dict) else {}
    raw_cover = _raw_cover_url(raw)
    source_type = note.source_type or "discovery"
    if source_type == "discovery":
        if raw.get("origin") == "publish":
            source_type = "publish"
        elif raw.get("source") == "creator_published":
            source_type = "creator"

    # Legacy rows may predate the metrics columns; fall back to raw_json.
    raw_metrics = extract_note_metrics(raw) if not (note.like_count or note.collect_count or note.comment_count or note.share_count) else {}
    likes = note.like_count or int(raw_metrics.get("likes") or 0)
    collects = note.collect_count or int(raw_metrics.get("collects") or 0)
    comments = note.comment_count or int(raw_metrics.get("comments") or 0)
    shares = note.share_count or int(raw_metrics.get("shares") or 0)
    fans = note.author_fans or int(raw.get("author_fans") or 0)
    like_fan_ratio = note.like_fan_ratio
    engagement_rate = note.engagement_rate
    if fans > 0 and not (like_fan_ratio or engagement_rate):
        rates = compute_note_metrics(likes, collects, comments, shares, fans)
        like_fan_ratio = like_fan_ratio or rates["like_fan_ratio"]
        engagement_rate = engagement_rate or rates["engagement_rate"]

    return {
        "id": note.id,
        "platform": note.platform,
        "platform_account_id": note.platform_account_id,
        "note_id": note.note_id,
        "title": note.title,
        # 正文**不截断**。
        #
        # 试过截到 400 字（为了省体积），活库 704 条里 407 条被截，代价是：
        #   · Library.tsx:279 的「字数」列显示 400，而 id=589 实际 914 字
        #   · Library.tsx:727 展开行只能看半篇
        #   · NotePreview 原文抽屉同样只到 400 字
        #   · Studio.tsx:516 语料总字数少算
        #   · Library.tsx:129 关键字搜不到 400 字之后的内容
        # 而真正撑大响应的是 raw_json（3,108K → 1,344K，省 57%），截正文只再省
        # 13%（1,344K → 703K）。不值得用五处错误换这 13%。
        "content": note.content,
        "author_name": note.author_name,
        "author_id": note.author_id or str(raw_metrics.get("author_id") or ""),
        "author_fans": fans,
        "source_type": source_type,
        "is_own": source_type in ("publish", "creator"),
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "shares": shares,
        "like_fan_ratio": like_fan_ratio,
        "engagement_rate": engagement_rate,
        "metrics_fetched_at": note.metrics_fetched_at.isoformat() if note.metrics_fetched_at else None,
        # 发布时间（作者发的），区别于 created_at（我们采的）。
        # 低粉爆款要按「最近几天」筛，用的就是这个字段；None 表示没读到，不是今天。
        "published_at": note.published_at.isoformat() if note.published_at else None,
        # 粉丝数是否真的采过。前端筛选要能区分「0 粉」和「没采到」。
        "author_fans_status": note.author_fans_status or "unknown",
        # 列表不返回原始抓取 payload：实测 page 6/7 单页 raw_json 有 596–665 KB，
        # 而整页其它字段加起来不到 100 KB。前端全部源码里 `raw_json` 出现 0 次，
        # 只有详情页需要它（`AssetPanel` 之外的调试视图）。brief=True 时省掉。
        "raw_json": (None if brief else note.raw_json),
        "asset_urls": asset_urls,
        "cover_url": _asset_display_url(image_assets[0]) if image_assets else raw_cover,
        "video_url": _asset_display_url(video_assets[0]) if video_assets else "",
        "video_addr": _asset_display_url(video_assets[0]) if video_assets else "",
        "created_at": note.created_at.isoformat(),
    }


def _serialize_note_with_tags(db: Session, note: Note, *, brief: bool = False) -> dict:
    serialized = _serialize_note(db, note, brief=brief)
    serialized["tags"] = _get_note_tags(db, note.id)
    return serialized


def _build_notes_csv(db: Session, notes: list[Note]) -> str:
    output = io.StringIO()
    fieldnames = [
        "note_id",
        "title",
        "author_id",
        "author_name",
        "author_fans",
        "likes",
        "collects",
        "comments",
        "shares",
        "like_fan_ratio",
        "engagement_rate",
        "content",
        "tags",
        "created_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for note in notes:
        tags = ",".join(tag["name"] for tag in _get_note_tags(db, note.id))
        serialized = _serialize_note(db, note)
        writer.writerow(
            {
                "note_id": note.note_id,
                "title": note.title,
                "author_id": serialized["author_id"],
                "author_name": note.author_name,
                "author_fans": serialized["author_fans"],
                "likes": serialized["likes"],
                "collects": serialized["collects"],
                "comments": serialized["comments"],
                "shares": serialized["shares"],
                "like_fan_ratio": serialized["like_fan_ratio"],
                "engagement_rate": serialized["engagement_rate"],
                "content": note.content,
                "tags": tags,
                "created_at": note.created_at.isoformat(),
            }
        )
    return output.getvalue()


def _serialize_asset(asset: NoteAsset) -> dict:
    return {
        "id": asset.id,
        "note_id": asset.note_id,
        "asset_type": asset.asset_type,
        "url": _asset_display_url(asset),
        "local_path": asset.local_path,
        "download_url": f"/api/files/media/{asset.local_path}" if asset.local_path else "",
        "sort_order": asset.sort_order,
    }


def _serialize_comment(comment: NoteComment) -> dict:
    return {
        "id": comment.id,
        "note_id": comment.note_id,
        "comment_id": comment.comment_id,
        "user_name": comment.user_name,
        "user_id": comment.user_id,
        "content": comment.content,
        "like_count": comment.like_count,
        "parent_comment_id": comment.parent_comment_id,
        "created_at_remote": comment.created_at_remote,
        "raw_json": comment.raw_json,
    }


def _serialize_draft(draft: AiDraft) -> dict:
    """Same payload as ``ai.py`` / ``drafts.py`` — see ``schemas/serializers.py``.

    This copy returned 6 of 18 fields, so ``batch-rewrite-drafts`` and
    ``batch-create-drafts`` handed callers drafts without ``tags``, ``context``
    or ``review_status``. The screen could not tell "empty" from "not returned".
    """
    return serialize_draft(draft)


def _get_owned_account(db: Session, current_user: User, account_id: int) -> PlatformAccount:
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id or account.platform != "xhs":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


def _get_latest_account_cookies(db: Session, account: PlatformAccount) -> str:
    from backend.app.services.account_cookies import latest_cookies

    try:
        return latest_cookies(db, account, missing_detail="Account has no cookies")
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


def _get_owned_note(db: Session, current_user: User, note_id: int) -> Note:
    note = db.get(Note, note_id)
    if note is None or note.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


class RefreshMetricsRequest(BaseModel):
    note_ids: list[int] = Field(default_factory=list, max_length=20)
    only_own: bool = False
    limit: int = Field(default=10, ge=1, le=20)


@router.post("/{note_id}/refresh-metrics")
def refresh_note_metrics(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    note = _get_owned_note(db, current_user, note_id)
    try:
        refresh_one_note(db, current_user, note, adapter_factory=adapter_factory)
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(note)
    return _serialize_note_with_tags(db, note)


@router.post("/refresh-metrics")
def refresh_notes_metrics(
    payload: RefreshMetricsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    if payload.note_ids:
        notes = [_get_owned_note(db, current_user, note_id) for note_id in payload.note_ids[: payload.limit]]
    else:
        statement = select(Note).where(Note.user_id == current_user.id)
        if payload.only_own:
            statement = statement.where(Note.source_type.in_(("publish", "creator")))
        notes = db.scalars(
            statement.order_by(Note.metrics_fetched_at.asc(), Note.created_at.desc())
            .limit(payload.limit)
        ).all()

    items: list[dict[str, Any]] = []
    updated = 0
    for note in notes:
        try:
            refresh_one_note(db, current_user, note, adapter_factory=adapter_factory)
            db.commit()
            db.refresh(note)
            updated += 1
            items.append(
                {
                    "note_id": note.id,
                    "status": "ok",
                    "note": _serialize_note_with_tags(db, note),
                }
            )
        except HTTPException as exc:
            db.rollback()
            items.append({"note_id": note.id, "status": "failed", "error": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            items.append({"note_id": note.id, "status": "failed", "error": str(exc)[:300]})

    return {"updated": updated, "failed": len(items) - updated, "items": items}


def _get_unique_owned_notes(db: Session, current_user: User, note_ids: list[int]) -> list[Note]:
    return [_get_owned_note(db, current_user, note_id) for note_id in dict.fromkeys(note_ids)]


class EnrichAuthorFansRequest(BaseModel):
    note_ids: list[int] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=5, ge=1, le=10)


@router.post("/enrich-author-fans")
def enrich_author_fans(    payload: EnrichAuthorFansRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    """Backfill author follower counts with strict limits.

    This is deliberately manual and bounded: it only fills a few authors per
    call, reuses cached counts, and never blocks saving notes if a profile
    lookup fails.
    """
    candidate_notes: list[Note] = []
    if payload.note_ids:
        candidate_notes = [
            _get_owned_note(db, current_user, note_id)
            for note_id in dict.fromkeys(payload.note_ids)
        ]
    else:
        candidate_notes = list(
            db.scalars(
                select(Note)
                .where(
                    Note.user_id == current_user.id,
                    Note.platform == "xhs",
                    Note.author_id != "",
                    # ``author_fans <= 0`` also matched notes whose count was a
                    # genuinely fetched zero, so those were re-fetched forever.
                    # Status is the reliable signal now.
                    Note.author_fans_status != "known",
                )
                .order_by(Note.created_at.desc())
                .limit(100)
            ).all()
        )

    groups: dict[str, list[Note]] = {}
    for note in candidate_notes:
        if not note.author_id or (note.author_fans_status or "unknown") == "known":
            continue
        groups.setdefault(note.author_id, []).append(note)
    author_ids = list(groups)[: payload.limit]
    if not author_ids:
        return {"authors_checked": 0, "notes_updated": 0, "failed": 0, "items": []}

    pc_account = None
    for item in candidate_notes:
        candidate_account = db.get(PlatformAccount, item.platform_account_id)
        if (
            candidate_account is not None
            and candidate_account.user_id == current_user.id
            and candidate_account.sub_type == "pc"
        ):
            pc_account = candidate_account
            break
    if pc_account is None:
        pc_account = db.scalars(
            select(PlatformAccount)
            .where(
                PlatformAccount.user_id == current_user.id,
                PlatformAccount.platform == "xhs",
                PlatformAccount.sub_type == "pc",
            )
            .order_by(PlatformAccount.updated_at.desc())
        ).first()
    if pc_account is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="补全粉丝需要一个已登录的 PC 账号")

    cookies = _get_latest_account_cookies(db, pc_account)
    adapter = adapter_factory(cookies)
    items: list[dict[str, Any]] = []
    notes_updated = 0
    failed = 0

    for index, author_id in enumerate(author_ids):
        group = groups[author_id]
        cached = db.scalars(
            select(Note).where(
                Note.user_id == current_user.id,
                Note.platform == "xhs",
                Note.author_id == author_id,
                Note.author_fans > 0,
            )
        ).first()
        fans = int(cached.author_fans) if cached else 0
        status_text = "cached"
        if fans <= 0:
            try:
                success, message, raw = adapter.get_user_info(author_id)
                if not success:
                    raise ValueError(message or "作者信息获取失败")
                profile = normalize_author_profile(raw)
                fans = int(profile.get("fans") or 0)
                if fans <= 0:
                    raise ValueError("未返回有效粉丝数")
                status_text = "fetched"
            except Exception as exc:  # noqa: BLE001
                failed += 1
                items.append(
                    {
                        "author_id": author_id,
                        "author_name": group[0].author_name,
                        "status": "failed",
                        "error": str(exc)[:200],
                    }
                )
                continue
            if index < len(author_ids) - 1:
                time.sleep(1.2)

        for note in db.scalars(
            select(Note).where(
                Note.user_id == current_user.id,
                Note.platform == "xhs",
                Note.author_id == author_id,
            )
        ).all():
            note.author_fans = fans
            # A successful lookup turns "unknown" into a real number, including a
            # genuine zero. Without this the status would stay unknown forever and
            # the backfill would never make the note usable for fan filtering.
            note.author_fans_status = "known"
            rates = compute_note_metrics(
                note.like_count or 0,
                note.collect_count or 0,
                note.comment_count or 0,
                note.share_count or 0,
                fans,
            )
            note.like_fan_ratio = rates["like_fan_ratio"]
            note.engagement_rate = rates["engagement_rate"]
            notes_updated += 1
        db.flush()
        items.append(
            {
                "author_id": author_id,
                "author_name": group[0].author_name,
                "status": status_text,
                "fans": fans,
            }
        )

    db.commit()
    return {
        "authors_checked": len(author_ids),
        "notes_updated": notes_updated,
        "failed": failed,
        "items": items,
    }


class BatchRewriteRequest(BaseModel):
    note_ids: list[int] = Field(min_length=1, max_length=5)
    account_id: Optional[int] = None
    instruction: str = Field(default="", max_length=1000)


@router.post("/batch-rewrite-drafts")
def batch_rewrite_to_drafts(
    payload: BatchRewriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    text_ai_client: TextAiClient = Depends(get_text_ai_client),
):
    """Turn saved notes into original drafts with AI rewriting.

    This is a *draft* workflow: no source images are copied, no publish job is
    created, and every result can be reviewed before scheduling.
    """
    require_risk_control(db, current_user, "batch_repost_enabled")
    notes = _get_unique_owned_notes(db, current_user, payload.note_ids)

    account = None
    if payload.account_id is not None:
        account = _get_owned_account(db, current_user, payload.account_id)

    persona_lines: list[str] = []
    if account is not None:
        # The persona table was removed; identity comes from the active Skill.
        persona_lines.append(f"请按账号「{account.nickname or account.id}」的定位和语气改写。")

    creation_skill = _load_creation_skill_text(db, current_user, payload.account_id)
    first_note = notes[0] if notes else None
    route_query = " ".join(
        part
        for part in [
            payload.instruction or "",
            (first_note.title or "") if first_note else "",
            ((first_note.content or "")[:300]) if first_note else "",
        ]
        if part
    )
    draft_library = module_skill_text(
        db,
        current_user,
        "draft",
        query=route_query,
        account_id=account.id if account is not None else None,
    )
    instruction = (
        (payload.instruction or "")
        + "\n请把参考笔记改写成一篇原创小红书笔记：保留主题和信息价值，"
        "但必须重写标题、开头、正文结构、例子和结尾；禁止逐字复制原句；"
        "不要编造没有依据的数据或经历；不要复制参考笔记的图片。\n"
        + "\n".join(persona_lines)
        + creation_skill
        + draft_library
    ).strip()

    model_config, api_key = _text_model_context(db, current_user)
    items: list[dict[str, Any]] = []
    created = 0
    for note in notes:
        try:
            raw = text_ai_client.rewrite_note(
                model_config=model_config,
                api_key=api_key,
                title=note.title or "",
                body=note.content or "",
                instruction=instruction,
            )
            title, body = parse_generated_note(raw)
            if not body.strip():
                raise ValueError("模型没有返回正文")
            draft = AiDraft(
                user_id=current_user.id,
                platform=note.platform,
                platform_account_id=account.id if account is not None else None,
                title=(title or note.title or "改写草稿")[:256],
                body=body.strip(),
                source_note_id=note.id,
                origin="batch_rewrite",
                skill_version=active_creation_skill_version(
                    db, current_user.id, account.id if account is not None else None
                ),
            )
            db.add(draft)
            db.commit()
            db.refresh(draft)
            similarity = SequenceMatcher(None, note.content or "", draft.body).ratio()
            warning = (
                "改写相似度较高，建议再人工调整结构和表达。"
                if similarity >= 0.8
                else ""
            )
            preflight = preflight_draft(
                db,
                current_user,
                draft,
                account_id=account.id if account is not None else None,
            )
            created += 1
            items.append(
                {
                    "source_note_id": note.id,
                    "draft": _serialize_draft(draft),
                    "similarity": round(similarity, 3),
                    "warning": warning,
                    "preflight": preflight,
                }
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            items.append(
                {
                    "source_note_id": note.id,
                    "status": "failed",
                    "error": str(exc)[:300],
                }
            )
    return {"created_count": created, "failed_count": len(items) - created, "items": items}


@router.get("/ids")
def get_note_ids(
    platform: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = (
        select(Note.note_id)
        .where(Note.user_id == current_user.id)
    )
    if platform:
        statement = statement.where(Note.platform == platform)
    note_ids = db.scalars(statement).all()
    return {"items": list(note_ids)}


@router.get("")
def get_notes(
    platform: Optional[str] = None,
    q: Optional[str] = None,
    tag_id: Optional[int] = None,
    has_assets: Optional[bool] = None,
    has_comments: Optional[bool] = None,
    source: Optional[Literal["all", "discovery", "publish", "creator", "own", "library"]] = None,
    max_fans: Optional[int] = Query(None, ge=0),
    min_likes: Optional[int] = Query(None, ge=0),
    min_like_fan_ratio: Optional[float] = Query(None, ge=0),
    # Recency by publication date, not crawl date. Notes whose date we never
    # captured are excluded: unknown age is not evidence of recency.
    published_within_days: Optional[int] = Query(None, ge=1, le=365),
    # Convenience switch for the shared low-follower definition. Kept as a flag so
    # the numbers live in one place (``low_follower.DEFAULT_RULE``) instead of
    # being re-typed by every caller.
    low_follower: bool = False,
    sort_by: Literal["created_at", "likes", "like_fan_ratio", "engagement_rate"] = "created_at",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = (
        select(Note)
        .where(Note.user_id == current_user.id)
    )
    if platform:
        statement = statement.where(Note.platform == platform)
    if source and source != "all":
        if source == "own":
            statement = statement.where(Note.source_type.in_(("publish", "creator")))
        elif source == "library":
            statement = statement.where(Note.source_type == "discovery")
        else:
            statement = statement.where(Note.source_type == source)
    if q:
        keyword = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Note.title.ilike(keyword),
                Note.content.ilike(keyword),
                Note.author_name.ilike(keyword),
                Note.note_id.ilike(keyword),
            )
        )
    if tag_id is not None:
        tag = db.get(Tag, tag_id)
        if tag is None or tag.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
        statement = statement.where(Note.id.in_(select(note_tags.c.note_id).where(note_tags.c.tag_id == tag_id)))
    if has_assets is True:
        statement = statement.where(Note.id.in_(select(NoteAsset.note_id)))
    elif has_assets is False:
        statement = statement.where(Note.id.not_in(select(NoteAsset.note_id)))
    if has_comments is True:
        statement = statement.where(Note.id.in_(select(NoteComment.note_id)))
    elif has_comments is False:
        statement = statement.where(Note.id.not_in(select(NoteComment.note_id)))
    unmeasured_fans = 0
    if max_fans is not None and max_fans > 0:
        # Only notes with a fetched follower count can be filtered by it. A note
        # whose count was never fetched is excluded here on purpose — including it
        # would assert something we do not know.
        statement = statement.where(
            Note.author_fans_status == "known",
            Note.author_fans <= max_fans,
        )
        # Count what the filter is about to hide. The dead
        # ``/analytics/low-fan-notes`` endpoint said this, but nothing called it;
        # on this path — the one the sample library actually uses — the number
        # just silently shrank.
        unmeasured_statement = (
            select(func.count())
            .select_from(Note)
            .where(
                Note.user_id == current_user.id,
                Note.author_fans_status != "known",
            )
        )
        if platform:
            unmeasured_statement = unmeasured_statement.where(Note.platform == platform)
        if source and source != "all":
            if source == "own":
                unmeasured_statement = unmeasured_statement.where(
                    Note.source_type.in_(("publish", "creator"))
                )
            elif source == "library":
                unmeasured_statement = unmeasured_statement.where(
                    Note.source_type == "discovery"
                )
            else:
                unmeasured_statement = unmeasured_statement.where(
                    Note.source_type == source
                )
        unmeasured_fans = db.scalar(unmeasured_statement) or 0
    if min_likes is not None and min_likes > 0:
        statement = statement.where(Note.like_count >= min_likes)
    if min_like_fan_ratio is not None and min_like_fan_ratio > 0:
        statement = statement.where(Note.like_fan_ratio >= min_like_fan_ratio)
    if low_follower:
        from backend.app.services.low_follower import DEFAULT_RULE

        # Same three thresholds as the rest of the product, sourced from one place.
        statement = statement.where(
            Note.author_fans_status == "known",
            Note.author_fans > 0,
            Note.author_fans <= DEFAULT_RULE.max_fans,
            Note.like_count >= DEFAULT_RULE.min_likes,
            Note.like_fan_ratio >= DEFAULT_RULE.min_like_fan_ratio,
        )
        if DEFAULT_RULE.within_days:
            from datetime import timedelta

            from backend.app.core.time import shanghai_now

            cutoff = shanghai_now() - timedelta(days=DEFAULT_RULE.within_days)
            statement = statement.where(Note.published_at.is_not(None), Note.published_at >= cutoff)
    if published_within_days is not None:
        from datetime import timedelta

        from backend.app.core.time import shanghai_now

        cutoff = shanghai_now() - timedelta(days=published_within_days)
        # ``published_at IS NOT NULL`` is part of the filter on purpose: a NULL
        # date must not slip through a "recent" query by comparing as unknown.
        statement = statement.where(Note.published_at.is_not(None), Note.published_at >= cutoff)
    if sort_by == "likes":
        order_by = (Note.like_count.desc(), Note.id.desc())
    elif sort_by == "like_fan_ratio":
        order_by = (Note.like_fan_ratio.desc(), Note.like_count.desc(), Note.id.desc())
    elif sort_by == "engagement_rate":
        order_by = (Note.engagement_rate.desc(), Note.like_count.desc(), Note.id.desc())
    else:
        order_by = (Note.created_at.desc(), Note.id.desc())
    # ① 先在 SQL 层分页：以前先取全表 704 行、对每行做 2 条 N+1（tags + assets），
    #   最后才切片。实测 page_size=1 与 =100 耗时都是 ~600ms、共 1,409 条 SQL，
    #   样本库首屏（8 页）因此要 5.8 秒。
    # ② total 用独立 count()，与当页无关；这与 publish_queue_service 的口径一致。
    total = db.scalar(
        select(func.count()).select_from(statement.subquery())
    ) or 0
    offset = (max(page, 1) - 1) * min(max(page_size, 1), 100)
    notes = db.scalars(
        statement.order_by(*order_by).offset(offset).limit(min(page_size, 100))
    ).all()
    extra = None
    if max_fans is not None and max_fans > 0 and unmeasured_fans:
        extra = {
            "unmeasured_fans": unmeasured_fans,
            "filter_note": (
                f"按粉丝数筛掉了 {unmeasured_fans} 篇未采集粉丝的样本；"
                "补采后它们才会参与筛选。"
            ),
        }
    return paginated(
        [_serialize_note_with_tags(db, note, brief=True) for note in notes],
        page,
        page_size,
        extra,
        total=total,
    )


@router.post("/batch-create-drafts")
def batch_create_drafts(
    payload: BatchCreateDraftsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notes = _get_unique_owned_notes(db, current_user, payload.note_ids)
    require_risk_control(db, current_user, "batch_repost_enabled")
    drafts: list[AiDraft] = []
    for note in notes:
        draft = AiDraft(
            user_id=current_user.id,
            platform=note.platform,
            title=note.title,
            body=note.content,
            source_note_id=note.id,
            origin="batch_create",
            skill_version=active_creation_skill_version(db, current_user.id, None),
        )
        db.add(draft)
        drafts.append(draft)

    db.commit()
    for draft in drafts:
        db.refresh(draft)

    return {
        "created_count": len(drafts),
        "items": [_serialize_draft(draft) for draft in drafts],
    }


@router.get("/{note_id}")
def get_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _serialize_note_with_tags(db, _get_owned_note(db, current_user, note_id))


@router.delete("/{note_id}")
def delete_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = _get_owned_note(db, current_user, note_id)
    db.execute(delete(note_tags).where(note_tags.c.note_id == note.id))
    db.execute(delete(NoteAsset).where(NoteAsset.note_id == note.id))
    db.execute(delete(NoteComment).where(NoteComment.note_id == note.id))
    db.query(AiDraft).filter(AiDraft.source_note_id == note.id).update({"source_note_id": None})
    db.delete(note)
    db.commit()
    return {"id": note_id, "status": "deleted"}


@router.get("/{note_id}/assets")
def get_note_assets(
    note_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = _get_owned_note(db, current_user, note_id)
    assets = db.scalars(select(NoteAsset).where(NoteAsset.note_id == note.id).order_by(NoteAsset.sort_order.asc(), NoteAsset.id.asc())).all()
    return paginated([_serialize_asset(asset) for asset in assets], page, page_size)


class AddNoteAssetRequest(BaseModel):
    asset_type: str = Field(pattern="^(image|video)$")
    url: str = Field(default="", max_length=2048)
    local_path: str = Field(default="", max_length=512)


@router.post("/{note_id}/assets")
def add_note_asset(
    note_id: int,
    payload: AddNoteAssetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = _get_owned_note(db, current_user, note_id)
    if not payload.url and not payload.local_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="url or local_path is required")
    asset = NoteAsset(
        note_id=note.id,
        asset_type=payload.asset_type,
        url=payload.url,
        local_path=payload.local_path,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _serialize_asset(asset)


@router.delete("/{note_id}/assets/{asset_id}")
def delete_note_asset(
    note_id: int,
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = _get_owned_note(db, current_user, note_id)
    asset = db.scalars(
        select(NoteAsset).where(NoteAsset.id == asset_id, NoteAsset.note_id == note.id)
    ).first()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    db.delete(asset)
    db.commit()
    return {"id": asset_id, "status": "deleted"}


class ReorderAssetsRequest(BaseModel):
    asset_ids: list[int] = Field(min_length=1)


@router.put("/{note_id}/assets/reorder")
def reorder_note_assets(
    note_id: int,
    payload: ReorderAssetsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = _get_owned_note(db, current_user, note_id)
    assets = db.scalars(select(NoteAsset).where(NoteAsset.note_id == note.id)).all()
    asset_map = {a.id: a for a in assets}
    for idx, aid in enumerate(payload.asset_ids):
        if aid in asset_map:
            asset_map[aid].sort_order = idx
    db.commit()
    return {"ok": True}


@router.get("/{note_id}/comments")
def get_note_comments(
    note_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = _get_owned_note(db, current_user, note_id)
    comments = db.scalars(
        select(NoteComment).where(NoteComment.note_id == note.id).order_by(NoteComment.id.asc())
    ).all()
    return paginated([_serialize_comment(comment) for comment in comments], page, page_size)


def _download_asset(url: str, user_id: int, asset_type: str) -> str | None:
    from backend.app.services.asset_downloader import download_asset_to_local
    return download_asset_to_local(url, user_id, asset_type)


@router.post("/batch-save")
def batch_save_notes(
    payload: BatchSaveNotesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    account = _get_owned_account(db, current_user, payload.account_id)
    comment_adapter = None
    if payload.fetch_comments:
        if account.sub_type != "pc":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PC account is required to fetch comments")
        comment_adapter = adapter_factory(_get_latest_account_cookies(db, account))
    saved_notes: list[Note] = []
    comment_warnings: list[dict[str, str]] = []

    # One IN query replaces one SELECT per note (100 notes previously meant
    # 100 round trips).  The dict also absorbs duplicate note_ids inside the
    # same payload so a repeated id updates the same row instead of hitting the
    # unique constraint.
    incoming_note_ids = list(dict.fromkeys(item.note_id for item in payload.notes))
    existing_by_note_id: dict[str, Note] = {}
    # Keep each IN (...) below SQLite's variable limit while still avoiding one
    # SELECT per note.
    #
    # 查询必须带 platform：唯一索引是 ``(user_id, platform, note_id)``，
    # 只按 ``note_id`` 找的话，同一个 id 字符串出现在另一个平台时会把那行
    # 认成本平台的旧记录并原地改写（platform / platform_account_id 都不重写），
    # 结果是抖音的转写稿被小红书 payload 覆盖，却仍标着 douyin。
    for start in range(0, len(incoming_note_ids), 500):
        chunk = incoming_note_ids[start : start + 500]
        existing_by_note_id.update({
            note.note_id: note
            for note in db.scalars(
                select(Note).where(
                    Note.user_id == current_user.id,
                    Note.platform == account.platform,
                    Note.note_id.in_(chunk),
                )
            ).all()
        })

    for note_payload in payload.notes:
        raw_payload = note_payload.raw if isinstance(note_payload.raw, dict) else {}
        inferred_source = (
            "publish"
            if raw_payload.get("origin") == "publish"
            else "creator"
            if raw_payload.get("source") == "creator_published"
            else "discovery"
        )
        existing = existing_by_note_id.get(note_payload.note_id)
        if existing is None:
            existing = Note(
                user_id=current_user.id,
                platform_account_id=account.id,
                platform=account.platform,
                note_id=note_payload.note_id,
                source_type=inferred_source,
            )
            db.add(existing)
            existing_by_note_id[note_payload.note_id] = existing
        elif inferred_source != "discovery":
            existing.source_type = inferred_source
        elif not existing.source_type:
            existing.source_type = "discovery"

        existing.title = note_payload.title
        existing.content = note_payload.content
        raw_metrics = extract_note_metrics(note_payload.raw)
        # `published_at` was the one field this path never wrote: every note
        # arrived with its publish time still sitting in `raw_json`, so 「最近
        # 发布」 filtered to zero and the low-follower breakout window missed
        # everything. It was not a parsing gap — `extract_note_metrics` already
        # returns the parsed datetime — the value was simply dropped on the
        # floor. Only fill NULLs: a re-crawl of an old note must not rewrite a
        # date we already resolved (and a payload with no time must not clear it).
        if existing.published_at is None:
            raw_published = raw_metrics.get("published_at")
            if raw_published is None and raw_payload:
                raw_published = parse_published_at(
                    raw_payload.get("published")
                    or raw_payload.get("published_at")
                    or raw_payload.get("workPublishTime")
                    or raw_payload.get("time")
                )
            if raw_published is not None:
                existing.published_at = raw_published
        existing.author_name = note_payload.author_name or str(raw_metrics.get("author_name") or "")
        existing.author_id = note_payload.author_id or str(raw_metrics.get("author_id") or "") or existing.author_id or ""
        existing.author_fans = note_payload.author_fans or existing.author_fans or 0
        # A caller that supplies a follower count has fetched it; one that omits
        # it has not. Recording that difference is the whole point of the status
        # column — otherwise every saved note looks like a zero-follower author.
        if note_payload.author_fans is not None and int(note_payload.author_fans) > 0:
            existing.author_fans_status = "known"
        elif (existing.author_fans_status or "unknown") != "known":
            existing.author_fans_status = "unknown"
        new_likes = int(note_payload.likes or raw_metrics.get("likes") or 0)
        new_collects = int(note_payload.collects or raw_metrics.get("collects") or 0)
        new_comments = int(note_payload.comments or raw_metrics.get("comments") or 0)
        new_shares = int(note_payload.shares or raw_metrics.get("shares") or 0)
        if new_likes > 0 or existing.like_count == 0:
            existing.like_count = new_likes
        if new_collects > 0 or existing.collect_count == 0:
            existing.collect_count = new_collects
        if new_comments > 0 or existing.comment_count == 0:
            existing.comment_count = new_comments
        if new_shares > 0 or existing.share_count == 0:
            existing.share_count = new_shares
        rates = compute_note_metrics(
            existing.like_count,
            existing.collect_count,
            existing.comment_count,
            existing.share_count,
            existing.author_fans,
        )
        existing.like_fan_ratio = note_payload.like_fan_ratio or rates["like_fan_ratio"]
        existing.engagement_rate = note_payload.engagement_rate or rates["engagement_rate"]
        from backend.app.services.memory_service import update_publish_metrics

        update_publish_metrics(
            db,
            user_id=current_user.id,
            note_id=existing.note_id,
            metrics={
                "likes": existing.like_count,
                "collects": existing.collect_count,
                "comments": existing.comment_count,
                "shares": existing.share_count,
                "engagement_rate": existing.engagement_rate,
            },
        )
        if existing.author_fans or existing.like_count or existing.collect_count or existing.comment_count or existing.share_count:
            existing.metrics_fetched_at = shanghai_now()
        merged_raw = dict(note_payload.raw) if note_payload.raw else {}
        if note_payload.note_url:
            merged_raw["note_url"] = note_payload.note_url
        existing.raw_json = merged_raw
        db.flush()
        record_note_analytics(db, existing, source="batch_save")
        db.execute(delete(NoteAsset).where(NoteAsset.note_id == existing.id))
        image_candidates = [*note_payload.image_urls] or ([note_payload.cover_url] if note_payload.cover_url else [])
        unique_image_urls = [url for index, url in enumerate(image_candidates) if url and url not in image_candidates[:index]]
        for image_url in unique_image_urls:
            local_name = _download_asset(image_url, current_user.id, "image")
            db.add(NoteAsset(note_id=existing.id, asset_type="image", url=image_url, local_path=local_name or ""))
        video_url = note_payload.video_url or note_payload.video_addr
        if video_url:
            local_name = _download_asset(video_url, current_user.id, "video")
            db.add(NoteAsset(note_id=existing.id, asset_type="video", url=video_url, local_path=local_name or ""))
        if payload.fetch_comments and note_payload.note_url and comment_adapter is not None:
            success, message, raw_payload = comment_adapter.get_note_comments(note_payload.note_url)
            if not success:
                # Comment fetching is best-effort: XHS frequently risk-controls it
                # (and it used to abort the whole batch). Save the note anyway.
                comment_warnings.append(
                    {
                        "note_id": note_payload.note_id,
                        "error": str(message or "获取评论失败"),
                    }
                )
            else:
                db.execute(delete(NoteComment).where(NoteComment.note_id == existing.id))
                for comment in normalize_comment_payload(raw_payload):
                    db.add(
                        NoteComment(
                            note_id=existing.id,
                            comment_id=comment["comment_id"],
                            user_name=comment["user_name"],
                            user_id=comment["user_id"],
                            content=comment["content"],
                            like_count=comment["like_count"],
                            parent_comment_id=comment["parent_comment_id"],
                            created_at_remote=comment["created_at_remote"],
                            raw_json=comment["raw_json"],
                        )
                    )
        saved_notes.append(existing)

    db.commit()
    for note in saved_notes:
        db.refresh(note)

    return {
        "saved_count": len(saved_notes),
        "comment_warnings": comment_warnings,
        "items": [_serialize_note_with_tags(db, note) for note in saved_notes],
    }


@router.post("/batch-tag")
def batch_tag_notes(
    payload: BatchTagNotesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notes: list[Note] = []
    for note_id in dict.fromkeys(payload.note_ids):
        notes.append(_get_owned_note(db, current_user, note_id))

    tag_ids = list(dict.fromkeys(payload.tag_ids))
    for tag_id in tag_ids:
        tag = db.get(Tag, tag_id)
        if tag is None or tag.user_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")

    for note in notes:
        if payload.mode == "replace":
            db.execute(delete(note_tags).where(note_tags.c.note_id == note.id))
            for tag_id in tag_ids:
                db.execute(note_tags.insert().values(note_id=note.id, tag_id=tag_id))
            continue

        if payload.mode == "add":
            existing_tag_ids = set(
                db.scalars(select(note_tags.c.tag_id).where(note_tags.c.note_id == note.id)).all()
            )
            for tag_id in tag_ids:
                if tag_id not in existing_tag_ids:
                    db.execute(note_tags.insert().values(note_id=note.id, tag_id=tag_id))
            continue

        if tag_ids:
            db.execute(
                delete(note_tags).where(
                    note_tags.c.note_id == note.id,
                    note_tags.c.tag_id.in_(tag_ids),
                )
            )

    db.commit()
    return {
        "updated_count": len(notes),
        "items": [_serialize_note_with_tags(db, note) for note in notes],
    }


@router.post("/export")
def export_notes(
    payload: ExportNotesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notes = _get_unique_owned_notes(db, current_user, payload.note_ids)
    export_dir = Path(get_settings().storage_dir) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    exported_at = shanghai_now()
    file_name = f"xhs-notes-u{current_user.id}-{exported_at.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}.{payload.format}"
    file_path = export_dir / file_name
    if payload.format == "csv":
        file_path.write_text("\ufeff" + _build_notes_csv(db, notes), encoding="utf-8")
    else:
        export_payload = {
            "platform": "xhs",
            "format": payload.format,
            "exported_at": exported_at.isoformat(),
            "total": len(notes),
            "items": [_serialize_note_with_tags(db, note) for note in notes],
        }
        file_path.write_text(json.dumps(export_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "exported_count": len(notes),
        "file_name": file_name,
        "file_path": str(file_path.resolve()),
        "download_url": f"/api/files/exports/{file_name}",
    }
