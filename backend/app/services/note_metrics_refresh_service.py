from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.api.platforms.xhs.pc import _cookies_to_string, _normalize_detail_payload
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import AccountCookieVersion, Note, PlatformAccount, User
from backend.app.services.memory_service import update_publish_metrics
from backend.app.services.note_metrics_service import compute_note_metrics

STALE_HOURS = 24
DEFAULT_LIMIT_PER_USER = 5


def _resolve_pc_account(db: Session, user: User, note: Note) -> PlatformAccount | None:
    account = db.get(PlatformAccount, note.platform_account_id)
    if (
        account is not None
        and account.user_id == user.id
        and account.sub_type == "pc"
    ):
        return account
    return db.scalars(
        select(PlatformAccount)
        .where(
            PlatformAccount.user_id == user.id,
            PlatformAccount.platform == note.platform,
            PlatformAccount.sub_type == "pc",
        )
        .order_by(PlatformAccount.updated_at.desc())
    ).first()


def _cookies_for_account(db: Session, account: PlatformAccount) -> str:
    from backend.app.services.account_cookies import latest_cookies

    try:
        return latest_cookies(db, account, missing_detail="账号没有可用 Cookie")
    except LookupError as exc:
        raise ValueError(str(exc)) from exc


def _note_url_with_token(raw: dict[str, Any], note_id: str) -> str:
    base = str(raw.get("note_url") or f"https://www.xiaohongshu.com/explore/{note_id}")
    token = str(raw.get("xsec_token") or "").strip()
    source = str(raw.get("xsec_source") or "pc_creatormng").strip() or "pc_creatormng"
    if token and "xsec_token=" not in base:
        separator = "&" if "?" in base else "?"
        base = f"{base}{separator}xsec_token={quote(token, safe='')}&xsec_source={quote(source, safe='')}"
    return base


def refresh_one_note(
    db: Session,
    user: User,
    note: Note,
    *,
    adapter_factory=XhsPcApiAdapter,
) -> Note:
    """Fetch fresh metrics for one note. Caller commits the session."""
    account = _resolve_pc_account(db, user, note)
    if account is None:
        if note.source_type in ("creator", "publish"):
            # Creator-only users have no PC account to refresh through. Advance
            # the timestamp so the hourly job does not retry the same notes
            # forever, and record the reason for the UI.
            raw = dict(note.raw_json or {})
            raw["metrics_error"] = "没有可用的 PC 账号，Creator 指标暂不支持自动刷新"
            note.raw_json = raw
            note.metrics_fetched_at = shanghai_now()
            db.flush()
            return note
        raise ValueError("没有可用的 PC 账号")

    cookies = _cookies_for_account(db, account)
    raw = note.raw_json if isinstance(note.raw_json, dict) else {}
    note_url = _note_url_with_token(raw, note.note_id)
    success, message, payload = adapter_factory(cookies).get_note_info(note_url)
    if not success:
        raise ValueError(message or "笔记详情获取失败")

    detail = _normalize_detail_payload(payload or {}, source_url=note_url)
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not items and isinstance(payload, dict):
        # 详情接口的 items 在顶层
        items = payload.get("items")
    if not items and not (detail.get("title") or detail.get("content")):
        raise ValueError(message or "笔记详情为空，可能暂时无法浏览")

    new_likes = int(detail.get("likes") or 0)
    new_collects = int(detail.get("collects") or 0)
    new_comments = int(detail.get("comments") or 0)
    new_shares = int(detail.get("shares") or 0)
    existing_has_metrics = any(
        (note.like_count, note.collect_count, note.comment_count, note.share_count)
    )
    if not any((new_likes, new_collects, new_comments, new_shares)) and existing_has_metrics:
        # Do not overwrite real metrics with zeros when the detail payload omits
        # interaction data. Keep the old numbers and retry on the next run.
        raise ValueError("详情未返回互动数据，已保留原指标")

    note.title = str(detail.get("title") or note.title or "")
    note.content = str(detail.get("content") or note.content or "")
    note.author_name = str(detail.get("author_name") or note.author_name or "")
    note.author_id = str(detail.get("author_id") or note.author_id or "")
    note.author_fans = int(detail.get("author_fans") or note.author_fans or 0)
    note.like_count = new_likes
    note.collect_count = new_collects
    note.comment_count = new_comments
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
    note.metrics_fetched_at = shanghai_now()

    refreshed_raw = dict(raw)
    refreshed_raw.update(
        {
            "note_url": note_url,
            "last_refreshed_at": note.metrics_fetched_at.isoformat(),
        }
    )
    note.raw_json = refreshed_raw

    if note.source_type in ("publish", "creator"):
        update_publish_metrics(
            db,
            user_id=user.id,
            note_id=note.note_id,
            metrics={
                "likes": note.like_count,
                "collects": note.collect_count,
                "comments": note.comment_count,
                "shares": note.share_count,
                "engagement_rate": note.engagement_rate,
            },
        )
    return note


def due_own_notes(
    db: Session,
    user: User,
    *,
    limit: int = DEFAULT_LIMIT_PER_USER,
    stale_hours: int = STALE_HOURS,
    now: datetime | None = None,
) -> list[Note]:
    now = now or shanghai_now()
    cutoff = now - timedelta(hours=stale_hours)
    return list(
        db.scalars(
            select(Note)
            .where(
                Note.user_id == user.id,
                Note.source_type.in_(("publish", "creator")),
                or_(Note.metrics_fetched_at.is_(None), Note.metrics_fetched_at < cutoff),
            )
            .order_by(Note.metrics_fetched_at.asc(), Note.created_at.asc())
            .limit(max(1, min(limit, 20)))
        ).all()
    )


def refresh_due_own_notes_for_user(
    db: Session,
    user: User,
    *,
    limit: int = DEFAULT_LIMIT_PER_USER,
    stale_hours: int = STALE_HOURS,
    adapter_factory=XhsPcApiAdapter,
) -> dict[str, Any]:
    notes = due_own_notes(db, user, limit=limit, stale_hours=stale_hours)
    items: list[dict[str, Any]] = []
    updated = 0
    for note in notes:
        try:
            refresh_one_note(db, user, note, adapter_factory=adapter_factory)
            db.commit()
            updated += 1
            items.append({"note_db_id": note.id, "note_id": note.note_id, "status": "ok"})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            items.append(
                {
                    "note_db_id": note.id,
                    "note_id": note.note_id,
                    "status": "failed",
                    "error": str(exc)[:300],
                }
            )
    return {"checked": len(notes), "updated": updated, "failed": len(notes) - updated, "items": items}


def refresh_due_own_notes_all_users(
    db: Session,
    *,
    limit_per_user: int = DEFAULT_LIMIT_PER_USER,
    stale_hours: int = STALE_HOURS,
    platform: str = "xhs",
    adapter_factory=XhsPcApiAdapter,
) -> dict[str, Any]:
    users = db.scalars(
        select(User)
        .join(Note, Note.user_id == User.id)
        .where(
            Note.platform == platform,
            Note.source_type.in_(("publish", "creator")),
        )
        .distinct()
        .order_by(User.id.asc())
    ).all()
    all_items: list[dict[str, Any]] = []
    updated = 0
    checked = 0
    for user in users:
        result = refresh_due_own_notes_for_user(
            db,
            user,
            limit=limit_per_user,
            stale_hours=stale_hours,
            adapter_factory=adapter_factory,
        )
        checked += result["checked"]
        updated += result["updated"]
        all_items.extend(result["items"])
    return {
        "users": len(users),
        "checked": checked,
        "updated": updated,
        "failed": checked - updated,
        "items": all_items,
    }
