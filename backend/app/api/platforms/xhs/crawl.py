from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Generator, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.api.platforms.xhs.pc import (
    _get_owned_pc_account_cookies,
    _normalize_detail_payload,
    _normalize_search_item,
    normalize_comment_payload,
    get_xhs_pc_api_adapter_factory,
)
from backend.app.api.tasks import serialize_task
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.models import Note, NoteAsset, PlatformAccount, Task, User
from backend.app.services.analytics_snapshot_service import record_note_analytics
from backend.app.services.note_metrics_service import compute_note_metrics, extract_note_metrics

router = APIRouter(prefix="/xhs/crawl", tags=["xhs-crawl"])
logger = logging.getLogger(__name__)


class CrawlSearchNotesRequest(BaseModel):
    account_id: int
    keyword: str = Field(min_length=1, max_length=120)
    page: int = Field(default=1, ge=1)
    save_to_library: bool = True
    fetch_comments: bool = False


class CrawlNoteUrlsRequest(BaseModel):
    account_id: int
    urls: list[str] = Field(min_length=1, max_length=50)
    save_to_library: bool = True
    fetch_comments: bool = False


class CrawlUserNotesRequest(BaseModel):
    account_id: int
    user_url: str = Field(min_length=1)
    save_to_library: bool = True


class DataCrawlRequest(BaseModel):
    account_id: int
    mode: Literal["note_urls", "search", "comments"]
    urls: list[str] = Field(default_factory=list, max_length=100)
    keyword: str = Field(default="", max_length=120)
    pages: int = Field(default=1, ge=1, le=20)
    max_notes: int = Field(default=20, ge=1, le=200)
    # Base delay between platform calls. 0 used to mean "no pause", which made the
    # default configuration the most bot-like one. Callers now get a timed pause
    # unless they explicitly pass 0 — and even then `_sleep_between_requests`
    # jitters a default band in, because a fixed rhythm is itself a signature.
    time_sleep: float = Field(default=1.5, ge=0, le=60)
    fetch_comments: bool = False
    sort_type_choice: int = Field(default=0, ge=0, le=4)
    note_type: int = Field(default=0, ge=0, le=2)
    note_time: int = Field(default=0, ge=0, le=3)
    note_range: int = Field(default=0, ge=0, le=3)
    pos_distance: int = Field(default=0, ge=0, le=2)
    geo: str = ""


def _serialize_note(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "platform": note.platform,
        "platform_account_id": note.platform_account_id,
        "note_id": note.note_id,
        "title": note.title,
        "content": note.content,
        "author_name": note.author_name,
        "raw_json": note.raw_json,
        "created_at": note.created_at.isoformat(),
    }


def _create_crawl_task(
    db: Session,
    current_user: User,
    crawl_type: str,
    payload: dict[str, Any],
) -> Task:
    task = Task(
        user_id=current_user.id,
        platform="xhs",
        task_type="crawl",
        status="running",
        progress=10,
        payload={"crawl_type": crawl_type, **payload},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _complete_task(db: Session, task: Task, payload: dict[str, Any]) -> Task:
    task.status = "completed"
    task.progress = 100
    task.payload = {**(task.payload or {}), **payload}
    db.commit()
    db.refresh(task)
    return task


def _fail_task(db: Session, task: Task, error: str) -> None:
    task.status = "failed"
    task.progress = 100
    task.payload = {**(task.payload or {}), "error": error}
    db.commit()


def _data_items(raw_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_payload, dict):
        return []
    data = raw_payload.get("data") if isinstance(raw_payload.get("data"), dict) else raw_payload
    items = data.get("items") or data.get("notes") or data.get("list") or []
    return [item for item in items if isinstance(item, dict) and item.get("model_type") not in ("rec_query", "hot_query")]


def _raw_with_metrics(normalized: dict[str, Any]) -> dict[str, Any]:
    raw = normalized.get("raw") if isinstance(normalized.get("raw"), dict) else {}
    return {
        **raw,
        "note_url": normalized.get("note_url", ""),
        "tags": normalized.get("tags", []),
        "type": normalized.get("type", ""),
        "likes": normalized.get("likes", 0),
        "collects": normalized.get("collects", 0),
        "comments": normalized.get("comments", 0),
        "shares": normalized.get("shares", 0),
    }


def _image_urls(normalized: dict[str, Any]) -> list[str]:
    urls = normalized.get("image_urls")
    if isinstance(urls, list) and urls:
        return [str(url) for url in urls if url]
    cover_url = normalized.get("cover_url")
    return [str(cover_url)] if cover_url else []


def _video_url(normalized: dict[str, Any]) -> str:
    return str(normalized.get("video_url") or normalized.get("video_addr") or "")


def _save_normalized_notes(
    db: Session,
    account: PlatformAccount,
    normalized_items: list[dict[str, Any]],
) -> list[Note]:
    saved: list[Note] = []
    now = shanghai_now()
    for normalized in normalized_items:
        note_id = str(normalized.get("note_id") or "").strip()
        if not note_id:
            continue
        note = db.scalars(
            select(Note).where(Note.user_id == account.user_id, Note.note_id == note_id)
        ).first()
        if note is None:
            note = Note(
                user_id=account.user_id,
                platform_account_id=account.id,
                platform=account.platform,
                note_id=note_id,
                source_type="discovery",
            )
            db.add(note)
        note.title = str(normalized.get("title") or "")
        note.content = str(normalized.get("content") or "")
        note.author_name = str(normalized.get("author_name") or "")
        raw_metrics = extract_note_metrics(normalized.get("raw") or normalized)
        note.author_id = str(
            normalized.get("author_id") or raw_metrics.get("author_id") or note.author_id or ""
        )
        new_fans = int(normalized.get("author_fans") or raw_metrics.get("author_fans") or 0)
        new_likes = int(normalized.get("likes") or raw_metrics.get("likes") or 0)
        new_collects = int(normalized.get("collects") or raw_metrics.get("collects") or 0)
        new_comments = int(normalized.get("comments") or raw_metrics.get("comments") or 0)
        new_shares = int(normalized.get("shares") or raw_metrics.get("shares") or 0)
        if new_fans > 0 or note.author_fans == 0:
            note.author_fans = new_fans
        # A feed payload often carries no follower count at all. Writing 0 without
        # a status is what made 97 notes look like zero-follower accounts, so the
        # status records whether the number was actually fetched.
        if new_fans > 0:
            note.author_fans_status = "known"
        elif not note.author_fans_status:
            note.author_fans_status = "unknown"
        if new_likes > 0 or note.like_count == 0:
            note.like_count = new_likes
        if new_collects > 0 or note.collect_count == 0:
            note.collect_count = new_collects
        if new_comments > 0 or note.comment_count == 0:
            note.comment_count = new_comments
        if new_shares > 0 or note.share_count == 0:
            note.share_count = new_shares
        rates = compute_note_metrics(
            note.like_count,
            note.collect_count,
            note.comment_count,
            note.share_count,
            note.author_fans,
        )
        note.like_fan_ratio = rates["like_fan_ratio"]
        note.engagement_rate = rates["engagement_rate"]
        if any(value > 0 for value in (new_likes, new_collects, new_comments, new_shares)) or note.metrics_fetched_at is None:
            note.metrics_fetched_at = now
        note.raw_json = _raw_with_metrics(normalized)
        # Prefer the adapter's already-normalized value; fall back to the raw
        # payload. Never overwrite a known date with None.
        published = normalized.get("published_at") or raw_metrics.get("published_at")
        if isinstance(published, datetime):
            note.published_at = published
        db.flush()
        record_note_analytics(db, note, source="crawl")
        db.execute(delete(NoteAsset).where(NoteAsset.note_id == note.id))
        for url in _image_urls(normalized):
            local_name = _download_asset(url, account.user_id, "image")
            db.add(NoteAsset(note_id=note.id, asset_type="image", url=url, local_path=local_name or ""))
        video_url = _video_url(normalized)
        if video_url:
            local_name = _download_asset(video_url, account.user_id, "video")
            db.add(NoteAsset(note_id=note.id, asset_type="video", url=video_url, local_path=local_name or ""))
        saved.append(note)

    db.commit()
    for note in saved:
        db.refresh(note)
    return saved


def _download_asset(url: str, user_id: int, asset_type: str) -> str | None:
    from backend.app.services.asset_downloader import download_asset_to_local
    return download_asset_to_local(url, user_id, asset_type)


def _sleep_between_requests(seconds: float) -> None:
    """Pause between platform calls, jittered within a safe band.

    The old version slept exactly ``seconds`` (or nothing when it was 0, which was
    the default). Both are risky: a fixed interval is a rhythm no human produces,
    and ``time_sleep=0`` meant the most common crawl path hammered the platform
    back to back.
    """
    from backend.app.services.crawl_guard import pick_delay

    delay = pick_delay(seconds)
    if delay > 0:
        time.sleep(min(delay, 60))


def _crawl_data_item(
    *,
    source: str,
    status: str,
    note: dict[str, Any] | None = None,
    comments: list[dict[str, Any]] | None = None,
    error: str = "",
) -> dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "error": error,
        "note": note,
        "comments": comments or [],
        "comment_count": len(comments or []),
    }


def _owned_pc_account(db: Session, current_user: User, account_id: int) -> PlatformAccount:
    account = db.get(PlatformAccount, account_id)
    if (
        account is None
        or account.user_id != current_user.id
        or account.platform != "xhs"
        or account.sub_type != "pc"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


@router.post("/search-notes")
def crawl_search_notes(
    payload: CrawlSearchNotesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    """Search one page. **Does not fetch note bodies.**

    Kept for compatibility, but prefer ``POST /xhs/crawl/data`` with
    ``mode="search"``: that path also fetches each note's detail (which needs the
    ``xsec_token`` carried on the search card) and therefore stores real content.
    Saving from this endpoint alone produces rows with an empty body — 99 such
    rows had to be backfilled on 2026-10-28 because this distinction was not
    written down anywhere.
    """
    account = _owned_pc_account(db, current_user, payload.account_id)
    cookies = _get_owned_pc_account_cookies(db, current_user, payload.account_id)
    task = _create_crawl_task(
        db,
        current_user,
        "search_notes",
        {"account_id": account.id, "keyword": payload.keyword, "page": payload.page},
    )
    success, message, raw_payload = adapter_factory(cookies).search_note(payload.keyword, page=payload.page)
    if not success:
        _fail_task(db, task, message or "XHS search crawl failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "XHS search crawl failed")

    normalized_items = [_normalize_search_item(item) for item in _data_items(raw_payload)]
    saved_notes = _save_normalized_notes(db, account, normalized_items) if payload.save_to_library else []
    task = _complete_task(
        db,
        task,
        {"result_count": len(normalized_items), "saved_count": len(saved_notes)},
    )
    return {
        "task": serialize_task(task),
        "result_count": len(normalized_items),
        "saved_count": len(saved_notes),
        "items": [_serialize_note(note) for note in saved_notes],
        "raw": raw_payload,
    }


@router.post("/note-urls")
def crawl_note_urls(
    payload: CrawlNoteUrlsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    account = _owned_pc_account(db, current_user, payload.account_id)
    cookies = _get_owned_pc_account_cookies(db, current_user, payload.account_id)
    task = _create_crawl_task(
        db,
        current_user,
        "note_urls",
        {"account_id": account.id, "url_count": len(payload.urls)},
    )
    adapter = adapter_factory(cookies)
    normalized_items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for index, url in enumerate(payload.urls):
        success, message, raw_payload = adapter.get_note_info(url)
        if success:
            normalized_items.append(_normalize_detail_payload(raw_payload or {}))
        else:
            errors.append({"url": url, "error": message or "XHS note detail crawl failed"})
        # This loop used to fire every detail request back to back — the most
        # bot-like pattern in the codebase. Pace it like the streaming endpoint.
        if index < len(payload.urls) - 1:
            _sleep_between_requests(1.5)

    saved_notes = _save_normalized_notes(db, account, normalized_items) if payload.save_to_library else []
    task = _complete_task(
        db,
        task,
        {"result_count": len(normalized_items), "saved_count": len(saved_notes), "errors": errors},
    )
    return {
        "task": serialize_task(task),
        "result_count": len(normalized_items),
        "saved_count": len(saved_notes),
        "errors": errors,
        "items": [_serialize_note(note) for note in saved_notes],
    }


@router.post("/user-notes")
def crawl_user_notes(
    payload: CrawlUserNotesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    """List one account's notes. **Does not fetch note bodies.**

    The account-notes listing carries the same card shape as search results, so
    titles and metrics are usable but ``content`` stays empty. Use
    ``POST /xhs/crawl/data`` with ``mode="note_urls"`` afterwards if the bodies
    are needed.
    """
    account = _owned_pc_account(db, current_user, payload.account_id)
    cookies = _get_owned_pc_account_cookies(db, current_user, payload.account_id)
    task = _create_crawl_task(
        db,
        current_user,
        "user_notes",
        {"account_id": account.id, "user_url": payload.user_url},
    )
    success, message, raw_payload = adapter_factory(cookies).get_user_notes(payload.user_url)
    if not success:
        _fail_task(db, task, message or "XHS user notes crawl failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "XHS user notes crawl failed")

    normalized_items = [_normalize_search_item(item) for item in _data_items(raw_payload)]
    saved_notes = _save_normalized_notes(db, account, normalized_items) if payload.save_to_library else []
    task = _complete_task(
        db,
        task,
        {"result_count": len(normalized_items), "saved_count": len(saved_notes)},
    )
    return {
        "task": serialize_task(task),
        "result_count": len(normalized_items),
        "saved_count": len(saved_notes),
        "items": [_serialize_note(note) for note in saved_notes],
        "raw": raw_payload,
    }


def _sse_event(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/data")
def crawl_data(
    payload: DataCrawlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    account = _owned_pc_account(db, current_user, payload.account_id)
    cookies = _get_owned_pc_account_cookies(db, current_user, payload.account_id)
    task = _create_crawl_task(
        db,
        current_user,
        f"data_{payload.mode}",
        {
            "account_id": account.id,
            "mode": payload.mode,
            "keyword": payload.keyword,
            "url_count": len(payload.urls),
            "pages": payload.pages,
            "time_sleep": payload.time_sleep,
        },
    )
    task_id = task.id
    account_id = account.id
    adapter = adapter_factory(cookies)

    def generate() -> Generator[str, None, None]:
        items: list[dict[str, Any]] = []
        normalized_for_save: list[dict[str, Any]] = []
        error_occurred = False

        try:
            if payload.mode == "note_urls":
                yield _sse_event({
                    "type": "plan",
                    "planned": len(payload.urls),
                    "pages": 0,
                })
                for index, url in enumerate(payload.urls):
                    success, message, raw_payload = adapter.get_note_info(url)
                    if success:
                        note = _normalize_detail_payload(raw_payload or {})
                        note["note_url"] = note.get("note_url") or url
                        normalized_for_save.append(note)
                        comments_list: list[dict[str, Any]] = []
                        if payload.fetch_comments:
                            cs, cm, cp = adapter.get_note_comments(url)
                            if cs:
                                comments_list = normalize_comment_payload(cp)
                            else:
                                item = _crawl_data_item(source=url, status="failed", note=note, error=cm or "comment crawl failed")
                                items.append(item)
                                yield _sse_event({"type": "item", "index": len(items) - 1, "processed": len(items), "item": item})
                                _sleep_between_requests(payload.time_sleep)
                                continue
                        item = _crawl_data_item(source=url, status="success", note=note, comments=comments_list)
                    else:
                        item = _crawl_data_item(source=url, status="failed", error=message or "detail crawl failed")
                    items.append(item)
                    yield _sse_event({"type": "item", "index": len(items) - 1, "processed": len(items), "item": item})
                    if index < len(payload.urls) - 1:
                        _sleep_between_requests(payload.time_sleep)

            elif payload.mode == "comments":
                yield _sse_event({
                    "type": "plan",
                    "planned": len(payload.urls),
                    "pages": 0,
                })
                for index, url in enumerate(payload.urls):
                    success, message, raw_payload = adapter.get_note_comments(url)
                    if success:
                        item = _crawl_data_item(source=url, status="success", comments=normalize_comment_payload(raw_payload))
                    else:
                        item = _crawl_data_item(source=url, status="failed", error=message or "comment crawl failed")
                    items.append(item)
                    yield _sse_event({"type": "item", "index": len(items) - 1, "processed": len(items), "item": item})
                    if index < len(payload.urls) - 1:
                        _sleep_between_requests(payload.time_sleep)

            else:
                if not payload.keyword.strip():
                    yield _sse_event({"type": "error", "message": "Keyword is required"})
                    return
                seen_urls: list[str] = []
                # Tell the client how many notes this run will attempt before the
                # first detail call, so the UI can show "3/20" instead of a spinner
                # with no denominator. `max_notes` is the cap; the real count can
                # only be lower (fewer search hits).
                yield _sse_event({
                    "type": "plan",
                    "planned": payload.max_notes,
                    "pages": payload.pages,
                })
                for page in range(1, payload.pages + 1):
                    success, message, raw_payload = adapter.search_note(
                        payload.keyword, page=page,
                        sort_type_choice=payload.sort_type_choice,
                        note_type=payload.note_type,
                        note_time=payload.note_time,
                        note_range=payload.note_range,
                        pos_distance=payload.pos_distance,
                        geo=payload.geo,
                    )
                    if not success:
                        item = _crawl_data_item(source=f"page:{page}", status="failed", error=message or "search failed")
                        items.append(item)
                        yield _sse_event({"type": "item", "index": len(items) - 1, "processed": len(items), "item": item})
                        break
                    yield _sse_event({"type": "progress", "message": f"搜索第 {page} 页完成，开始获取详情..."})
                    for raw_item in _data_items(raw_payload):
                        if len(items) >= payload.max_notes:
                            break
                        search_note = _normalize_search_item(raw_item)
                        note_url = search_note.get("note_url") or ""
                        source = note_url or str(search_note.get("note_id") or f"page:{page}")
                        if source in seen_urls:
                            continue
                        seen_urls.append(source)
                        detail_note = search_note
                        detail_error = ""
                        if note_url:
                            ds, dm, dp = adapter.get_note_info(note_url)
                            if ds:
                                detail_note = _normalize_detail_payload(dp or {}, source_url=note_url)
                                detail_note["note_url"] = detail_note.get("note_url") or note_url
                                if not (detail_note.get("content") or "").strip():
                                    detail_error = "详情无正文，可能已删除或受限"
                            else:
                                # Keep the search payload: title and metrics are
                                # still useful, and the note can be backfilled
                                # later instead of vanishing from the library.
                                detail_error = dm or "detail failed"
                        comments_list = []
                        if payload.fetch_comments and note_url:
                            cs, cm, cp = adapter.get_note_comments(note_url)
                            if cs:
                                comments_list = normalize_comment_payload(cp)
                            else:
                                # Comments are optional; keep the note itself.
                                detail_error = detail_error or (cm or "comment failed")
                        normalized_for_save.append(detail_note)
                        item = _crawl_data_item(
                            source=source,
                            status="partial" if detail_error else "success",
                            note=detail_note,
                            comments=comments_list,
                            error=detail_error,
                        )
                        items.append(item)
                        yield _sse_event({"type": "item", "index": len(items) - 1, "processed": len(items), "item": item})
                        _sleep_between_requests(payload.time_sleep)
                    if len(items) >= payload.max_notes:
                        break
                    data = (raw_payload or {}).get("data") or {}
                    if not data.get("has_more", False):
                        break

        except Exception as exc:
            error_occurred = True
            yield _sse_event({"type": "error", "message": str(exc)})

        success_count = len([i for i in items if i["status"] in ("success", "partial")])
        failed_count = len(items) - success_count
        saved_count = 0
        if normalized_for_save:
            from backend.app.core.database import SessionLocal
            from backend.app.models import PlatformAccount

            save_db = SessionLocal()
            try:
                save_account = save_db.get(PlatformAccount, account_id)
                if save_account is not None:
                    _save_normalized_notes(save_db, save_account, normalized_for_save)
                    save_db.commit()
                    saved_count = len(normalized_for_save)
            except Exception:
                save_db.rollback()
                logger.warning("SSE crawl save failed", exc_info=True)
            finally:
                save_db.close()
        try:
            if error_occurred:
                _fail_task(db, task, "partial failure")
            else:
                _complete_task(
                    db,
                    task,
                    {
                        "result_count": success_count,
                        "failed_count": failed_count,
                        "saved_count": saved_count,
                    },
                )
        except Exception:
            pass

        yield _sse_event({
            "type": "done",
            "task_id": task_id,
            "total": len(items),
            "success_count": success_count,
            "failed_count": failed_count,
            "saved_count": saved_count,
        })

    return StreamingResponse(generate(), media_type="text/event-stream")
