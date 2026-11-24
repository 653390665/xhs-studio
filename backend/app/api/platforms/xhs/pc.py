from __future__ import annotations

import json
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.provider import resolve_redfox_adapter, resolve_xhs_api_adapter
from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.models import AccountCookieVersion, Note, NoteComment, PlatformAccount, User
from backend.app.services.note_metrics_service import (
    enrich_items_with_authors,
    filter_and_sort_items,
    normalize_author_profile,
    parse_count,
)

router = APIRouter(prefix="/xhs/pc", tags=["xhs-pc"])


class SearchNotesRequest(BaseModel):
    account_id: int
    keyword: str = Field(min_length=1, max_length=120)
    page: int = Field(default=1, ge=1)
    sort_type_choice: int = Field(default=0, ge=0, le=4)
    note_type: int = Field(default=0, ge=0, le=2)
    note_time: int = Field(default=0, ge=0, le=3)
    note_range: int = Field(default=0, ge=0, le=3)
    pos_distance: int = Field(default=0, ge=0, le=2)
    geo: str = ""
    enrich_authors: bool = False
    min_likes_for_profile: int = Field(default=0, ge=0)
    max_profiles: int = Field(default=10, ge=1, le=20)
    max_fans: int = Field(default=0, ge=0)
    min_likes: int = Field(default=0, ge=0)
    min_like_fan_ratio: float = Field(default=0.0, ge=0)
    # Recency window in days. 0 = no window. Client-side on purpose: the note
    # listing payload carries ``time`` for every card, so this needs no extra
    # request, unlike follower counts.
    within_days: int = Field(default=0, ge=0, le=365)
    sort_by: Literal["default", "likes", "like_fan_ratio", "engagement_rate"] = "default"


class UserInfoRequest(BaseModel):
    account_id: int
    user_id: str = Field(min_length=1, max_length=128)


class UserNotesRequest(BaseModel):
    account_id: int
    # Accepts a bare author id, a full profile URL, or a profile URL carrying
    # xsec_token. The adapter resolves all three.
    user_id: str = Field(min_length=1, max_length=512)
    xsec_token: str = Field(default="", max_length=256)
    limit: int = Field(default=20, ge=1, le=50)


class NoteDetailRequest(BaseModel):
    account_id: int
    url: str = Field(min_length=1)


class NoteCommentsRequest(BaseModel):
    account_id: int
    note_url: str = Field(min_length=1)


def get_xhs_pc_api_adapter_factory():
    """Provider-aware adapter factory (pc by default, redfox when configured)."""
    return resolve_xhs_api_adapter


def get_xhs_redfox_adapter_factory():
    """Factory for the RedFox-only features, independent of the PC provider."""
    return resolve_redfox_adapter


@router.get("/provider")
def get_provider_status(current_user: User = Depends(get_current_user)):
    """Report which XHS data provider is active and today's RedFox usage."""
    from backend.app.adapters.xhs.redfox_api_adapter import redfox_usage_snapshot

    settings = get_settings()
    configured = (settings.xhs_data_provider or "pc").strip().lower()
    effective = "redfox" if (configured == "redfox" and settings.redfox_api_key) else "pc"
    return {
        "configured_provider": configured,
        "effective_provider": effective,
        "redfox_configured": bool(settings.redfox_api_key),
        "redfox_api_base_url": settings.redfox_api_base_url,
        "redfox_daily_call_limit": settings.redfox_daily_call_limit,
        "redfox_usage": redfox_usage_snapshot(),
    }


def _cookies_to_string(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return stripped
    if stripped.startswith("{"):
        cookies = json.loads(stripped)
        return "; ".join(f"{key}={cookie_value}" for key, cookie_value in cookies.items())
    return stripped


def _metric(value: Any) -> int:
    return parse_count(value)


def _first_url(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _first_url(value[0])
    if isinstance(value, dict):
        info_list = value.get("info_list")
        if isinstance(info_list, list) and len(info_list) > 1 and isinstance(info_list[1], dict):
            preferred_url = info_list[1].get("url")
            if preferred_url:
                return str(preferred_url)
        for key in ("url_default", "url_pre", "url", "src"):
            if value.get(key):
                return str(value[key])
        for nested in ("info_list", "image_list", "images"):
            if value.get(nested):
                return _first_url(value[nested])
    return ""


def _all_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        urls: list[str] = []
        for item in value:
            urls.extend(_all_urls(item))
        return [url for index, url in enumerate(urls) if url and url not in urls[:index]]
    if isinstance(value, dict):
        direct = _first_url(value)
        if direct:
            return [direct]
        urls: list[str] = []
        for nested in ("info_list", "image_list", "images"):
            if value.get(nested):
                urls.extend(_all_urls(value[nested]))
        return [url for index, url in enumerate(urls) if url and url not in urls[:index]]
    return []


def _tag_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    tags: list[str] = []
    for item in value:
        if isinstance(item, str):
            tag = item
        elif isinstance(item, dict):
            tag = item.get("name") or item.get("tag_name") or item.get("title") or ""
        else:
            tag = ""
        if tag and tag not in tags:
            tags.append(str(tag))
    return tags


def _note_url(note_id: str, item: dict[str, Any], card: dict[str, Any]) -> str:
    xsec_token = card.get("xsec_token") or item.get("xsec_token") or ""
    if note_id and xsec_token:
        xsec_source = card.get("xsec_source") or item.get("xsec_source") or "pc_feed"
        return f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source={xsec_source}"
    for value in (
        card.get("note_url"),
        card.get("url"),
        card.get("share_url"),
        item.get("note_url"),
        item.get("url"),
        item.get("share_url"),
    ):
        if isinstance(value, str) and value:
            return value
    if not note_id:
        return ""
    return f"https://www.xiaohongshu.com/explore/{note_id}"


def _comment_id(comment: dict[str, Any]) -> str:
    return str(comment.get("comment_id") or comment.get("id") or comment.get("commentId") or "")


def _comment_user(comment: dict[str, Any]) -> dict[str, Any]:
    return comment.get("user_info") or comment.get("user") or comment.get("author") or {}


def _comment_children(comment: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("sub_comments", "sub_comment", "comments", "replies", "children"):
        value = comment.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    sub_comment_payload = comment.get("sub_comment_info")
    if isinstance(sub_comment_payload, dict):
        value = sub_comment_payload.get("comments")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _normalize_comment(comment: dict[str, Any], parent_comment_id: str | None = None) -> dict[str, Any]:
    user = _comment_user(comment)
    return {
        "comment_id": _comment_id(comment),
        "user_name": str(user.get("nickname") or user.get("name") or comment.get("user_name") or ""),
        "user_id": str(user.get("user_id") or user.get("id") or comment.get("user_id") or "") or None,
        "content": str(comment.get("content") or comment.get("text") or comment.get("desc") or ""),
        "like_count": _metric(comment.get("like_count") or comment.get("liked_count") or comment.get("likes")),
        "parent_comment_id": parent_comment_id,
        "created_at_remote": comment.get("create_time") or comment.get("created_at") or comment.get("time"),
        "raw_json": comment,
    }


def _flatten_comments(comments: list[dict[str, Any]], parent_comment_id: str | None = None) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for comment in comments:
        normalized = _normalize_comment(comment, parent_comment_id=parent_comment_id)
        if normalized["comment_id"]:
            flattened.append(normalized)
            child_parent_id = normalized["comment_id"]
        else:
            child_parent_id = parent_comment_id
        flattened.extend(_flatten_comments(_comment_children(comment), parent_comment_id=child_parent_id))
    return flattened


def _extract_comment_list(raw_payload: Any) -> list[dict[str, Any]]:
    if isinstance(raw_payload, list):
        return [item for item in raw_payload if isinstance(item, dict)]
    if not isinstance(raw_payload, dict):
        return []
    data = raw_payload.get("data") if isinstance(raw_payload.get("data"), dict) else raw_payload
    for key in ("comments", "items", "list"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def normalize_comment_payload(raw_payload: Any) -> list[dict[str, Any]]:
    return _flatten_comments(_extract_comment_list(raw_payload))


def _normalize_search_item(item: dict[str, Any]) -> dict[str, Any]:
    card = item.get("note_card") or item.get("note") or item
    author = card.get("user") or card.get("author") or {}
    interact = card.get("interact_info") or card.get("interaction") or {}
    note_id = card.get("note_id") or card.get("id") or item.get("id") or ""
    timestamp = card.get("time") or card.get("create_time") or item.get("time") or item.get("create_time") or 0
    from backend.app.services.note_metrics_service import parse_published_at

    return {
        "note_id": note_id,
        "note_url": _note_url(str(note_id), item, card),
        "title": card.get("display_title") or card.get("title") or "",
        "content": card.get("desc") or card.get("content") or "",
        "author_id": author.get("user_id") or author.get("id") or "",
        "author_name": author.get("nickname") or author.get("name") or "",
        "author_avatar": author.get("avatar") or author.get("avatar_url") or "",
        "cover_url": _first_url(card.get("cover") or card.get("image_list") or card.get("images")),
        "image_urls": _all_urls(card.get("image_list") or card.get("images") or card.get("cover")),
        "likes": _metric(interact.get("liked_count") or interact.get("likes")),
        "collects": _metric(interact.get("collected_count") or interact.get("collects")),
        "comments": _metric(interact.get("comment_count") or interact.get("comments")),
        "shares": _metric(interact.get("share_count") or interact.get("shares")),
        "type": card.get("type") or item.get("model_type") or "",
        "timestamp": timestamp,
        # Parsed once here so downstream filters do not each re-guess the format.
        "published_at": parse_published_at(timestamp),
        "raw": item,
    }


def _video_url(card: dict[str, Any]) -> str:
    for key in ("video_addr", "video_url"):
        if card.get(key):
            return str(card[key])
    video_info = card.get("video") if isinstance(card.get("video"), dict) else {}
    stream_info = video_info.get("media", {}).get("stream", {}) if isinstance(video_info, dict) else {}
    if not isinstance(stream_info, dict):
        stream_info = {}
    # 新版 Web 把编码名混淆为 EF4(h264) / EF5(h265) 等，优先兼容性最好的 h264
    preferred = ["h264", "EF4", "h265", "EF5", "av1"]
    codecs = preferred + [codec for codec in stream_info if codec not in preferred]
    for codec in codecs:
        streams = stream_info.get(codec)
        if not isinstance(streams, list):
            continue
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            candidates = [stream.get("master_url"), stream.get("url")]
            backup_urls = stream.get("backup_urls")
            if isinstance(backup_urls, list):
                candidates.extend(backup_urls)
            for candidate in candidates:
                if candidate:
                    return str(candidate)
    consumer = video_info.get("consumer") if isinstance(video_info.get("consumer"), dict) else {}
    origin_key = consumer.get("origin_video_key")
    return f"https://sns-video-bd.xhscdn.com/{origin_key}" if origin_key else ""


def _normalize_detail_payload(raw_payload: dict[str, Any], source_url: str = "") -> dict[str, Any]:
    data = (raw_payload or {}).get("data") or {}
    # 详情接口把 items 放在顶层，搜索接口才包在 data 里。只认 data.items 时，
    # 详情采集拿不到封面/图片列表/发布时间，而且不报错。
    items = data.get("items") if isinstance(data, dict) else None
    if not items and isinstance((raw_payload or {}).get("items"), list):
        items = raw_payload["items"]
    items = items or []
    item = items[0] if items and isinstance(items[0], dict) else (data if isinstance(data, dict) else {})
    normalized = _normalize_search_item(item)
    card = item.get("note_card") or item.get("note") or item
    images = _all_urls(card.get("image_list") or card.get("images") or card.get("cover"))
    if source_url:
        normalized["note_url"] = source_url
    normalized["image_urls"] = images
    video_url = _video_url(card)
    normalized["video_url"] = video_url
    normalized["video_addr"] = video_url
    normalized["tags"] = _tag_names(card.get("tag_list") or card.get("tags") or card.get("topics"))
    normalized["raw"] = raw_payload
    return normalized


def _effective_provider() -> str:
    """Resolve the active provider, failing with a clean HTTP error if misconfigured."""
    settings = get_settings()
    configured = (settings.xhs_data_provider or "pc").strip().lower()
    if configured == "redfox":
        if not settings.redfox_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "已将 xhs_provider.data_provider 设为 redfox，但未配置 redfox_api_key。"
                    "请设置 REDFOX_API_KEY（或 config/default.yaml 的 xhs_provider.redfox_api_key）。"
                ),
            )
        return "redfox"
    return "pc"


def _resolve_cookies(db: Session, current_user: User, account_id: int) -> str:
    """Return the cookies the adapter should use.

    RedFox authenticates with an API key and does not need an XHS login, so no PC
    account is required when it is the effective provider (``account_id`` is then
    ignored). The default PC provider still requires an owned account with
    cookies, exactly as before.
    """
    if _effective_provider() == "redfox":
        return ""
    return _get_owned_pc_account_cookies(db, current_user, account_id)


def _get_owned_pc_account_cookies(db: Session, current_user: User, account_id: int) -> str:
    account = db.get(PlatformAccount, account_id)
    if (
        account is None
        or account.user_id != current_user.id
        or account.platform != "xhs"
        or account.sub_type != "pc"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    from backend.app.services.account_cookies import latest_cookies

    try:
        return latest_cookies(db, account, missing_detail="Account has no cookies")
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/accounts/{account_id}/creator-bridge")
def check_creator_bridge_for_account(
    account_id: int,
    keyword: str = Query(default="小红书", max_length=60),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """一次性登录检测：PC 账号的 Cookie 能否直接驱动创作者中心接口。

    ``keyword`` 只是连通性探测用的公开话题，与账号赛道无关，可自行传入。
    只做一次只读探测，不保存任何东西，也不改动现有登录流程。
    """
    cookies = _get_owned_pc_account_cookies(db, current_user, account_id)
    from backend.app.services.xhs_unified_auth_service import check_creator_bridge

    result = check_creator_bridge(cookies, keyword=keyword)
    result["account_id"] = account_id
    return result


@router.post("/search/notes")
def search_notes(
    payload: SearchNotesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    """Search one page for preview. **Bodies are empty by design.**

    The search listing is a card feed: it carries title, cover, metrics and an
    ``xsec_token``, but no ``desc``. Fetching a body needs a second call to the
    detail endpoint, signed with that token.

    This is the cheapest call in the app (one platform request per page), which
    is why the discovery screen uses it for browsing. It is **not** a collector:
    saving its results straight to the library produces notes with no content.
    For collection use ``POST /xhs/crawl/data`` with ``mode="search"``, which
    fetches each detail in turn.
    """
    cookies = _resolve_cookies(db, current_user, payload.account_id)
    success, message, raw_payload = adapter_factory(cookies).search_note(
        payload.keyword,
        page=payload.page,
        sort_type_choice=payload.sort_type_choice,
        note_type=payload.note_type,
        note_time=payload.note_time,
        note_range=payload.note_range,
        pos_distance=payload.pos_distance,
        geo=payload.geo,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message or "XHS note search failed",
        )

    data = (raw_payload or {}).get("data") or {}
    items = data.get("items") or []
    normalized_items = [
        _normalize_search_item(item)
        for item in items
        if isinstance(item, dict) and item.get("model_type") not in ("rec_query", "hot_query")
    ]
    raw_total = len(normalized_items)

    needs_fans = (
        payload.max_fans > 0
        or payload.min_like_fan_ratio > 0
        or payload.sort_by in ("like_fan_ratio", "engagement_rate")
    )
    enrichment = None
    if payload.enrich_authors or needs_fans:
        enrichment = enrich_items_with_authors(
            adapter_factory(cookies),
            normalized_items,
            min_likes_for_profile=payload.min_likes_for_profile or payload.min_likes,
            max_profiles=payload.max_profiles,
        )
    normalized_items = filter_and_sort_items(
        normalized_items,
        max_fans=payload.max_fans,
        min_likes=payload.min_likes,
        min_like_fan_ratio=payload.min_like_fan_ratio,
        within_days=payload.within_days,
        sort_by=payload.sort_by,
    )
    return {
        "total": len(normalized_items),
        "raw_total": raw_total,
        "filtered_total": len(normalized_items),
        "filtered_out": max(0, raw_total - len(normalized_items)),
        "page": payload.page,
        "page_size": data.get("page_size") or 20,
        "has_more": bool(data.get("has_more", False)),
        "items": normalized_items,
        "enrichment": enrichment,
        # Say what the filters actually did. "3 results" alone cannot be told
        # apart from "we filtered 17 out because their follower count is
        # unknown", and those two mean opposite things to the user.
        "filter_summary": {
            "max_fans": payload.max_fans,
            "min_likes": payload.min_likes,
            "min_like_fan_ratio": payload.min_like_fan_ratio,
            "within_days": payload.within_days,
            "raw_total": raw_total,
            "kept": len(normalized_items),
            "dropped": max(0, raw_total - len(normalized_items)),
            "unmeasured_fans": sum(
                1 for item in normalized_items if int(item.get("author_fans") or 0) <= 0
            ),
        },
        # Explicit, because it is not inferable from the data: these items have
        # titles and metrics but no body. A caller that saves them to the library
        # without fetching details silently creates empty-content notes.
        "bodies_included": any((item.get("content") or "").strip() for item in normalized_items),
        "raw": raw_payload,
    }


@router.post("/users/info")
def user_info(
    payload: UserInfoRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    cookies = _resolve_cookies(db, current_user, payload.account_id)
    success, message, raw_payload = adapter_factory(cookies).get_user_info(payload.user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message or "XHS user profile failed",
        )
    profile = normalize_author_profile(raw_payload)
    if not profile:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="XHS user profile is empty")
    return profile


def _profile_url(user_id_or_url: str, xsec_token: str = "") -> str:
    """Normalise an author id / profile URL into the URL the adapter parses."""
    from urllib.parse import urlencode, urlparse

    raw = (user_id_or_url or "").strip()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请提供作者 ID 或主页链接")

    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        # Already carries its own token: the adapter will pick it up.
        if "xsec_token" in (parsed.query or ""):
            return raw
        author_id = parsed.path.rstrip("/").split("/")[-1]
        url = f"https://www.xiaohongshu.com/user/profile/{author_id}"
    elif "/" in raw:
        # Path-ish input such as "user/profile/<id>".
        author_id = raw.rstrip("/").split("/")[-1]
        url = f"https://www.xiaohongshu.com/user/profile/{author_id}"
    else:
        author_id = raw
        url = f"https://www.xiaohongshu.com/user/profile/{raw}"

    # XHS author ids are 24 hex chars. A truncated id is indistinguishable from
    # "this account has no public notes" — the platform answers
    # ``{success: true, data: null}`` and the caller concludes the account is
    # private or rate-limited. Reject it here so the message names the real
    # cause instead of blaming the platform.
    if not re.fullmatch(r"[0-9a-f]{24}", author_id or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"作者 ID 格式不正确：{author_id!r}（{len(author_id)} 位）。"
                "小红书作者 ID 是 24 位十六进制字符串，"
                "常见错误是从终端回显里抄被截断的 ID。"
            ),
        )

    if xsec_token.strip():
        url = f"{url}?{urlencode({'xsec_token': xsec_token.strip(), 'xsec_source': 'pc_search'})}"
    return url


@router.post("/users/notes")
def user_notes(
    payload: UserNotesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    """作者的公开作品列表（用于从笔记发现跳到"看这个账号的全部内容"）。"""
    cookies = _resolve_cookies(db, current_user, payload.account_id)

    # ``get_user_notes`` expects a profile URL, not a bare id: it parses the id
    # and xsec_token out of the path and query. Passing "663848c2…" made
    # urllib return an empty path segment and the SDK raised
    # ``'NoneType' object is not subscriptable`` — every call 502'd. Accept an
    # id, a full URL, or a URL with xsec_token, which is what callers actually
    # have.
    profile_url = _profile_url(payload.user_id, payload.xsec_token)
    success, message, notes = adapter_factory(cookies).get_user_notes(profile_url)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message or "XHS user notes failed",
        )

    raw_notes = notes if isinstance(notes, list) else []

    items = []
    for note in raw_notes[: payload.limit]:
        if not isinstance(note, dict):
            continue
        items.append(_normalize_search_item(note))
    return {"items": items, "total": len(raw_notes)}


@router.post("/notes/detail")
def note_detail(
    payload: NoteDetailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    cookies = _resolve_cookies(db, current_user, payload.account_id)
    success, message, raw_payload = adapter_factory(cookies).get_note_info(payload.url)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message or "XHS note detail failed",
        )
    # XHS answers 200 with an empty ``data`` and a business code for deleted,
    # private, or rate-limited notes. Returning success here silently blanked
    # the note's title/content, so callers must see a real error instead.
    detail_error = _detail_business_error(raw_payload or {})
    if detail_error:
        # ``code`` lets the client tell a temporary XHS soft-block (wait and
        # retry) apart from a permanently dead note (skip and mark unavailable).
        # Both used to be an opaque 502, so batch backfill could not back off.
        raise HTTPException(
            status_code=_detail_error_status(raw_payload or {}),
            detail=detail_error,
            headers={"X-XHS-Reason": _detail_error_kind(raw_payload or {})},
        )
    return _normalize_detail_payload(raw_payload or {}, source_url=payload.url)


# XHS business codes that mean "this note cannot be opened", split by whether
# retrying later can plausibly succeed.
_DETAIL_RATE_LIMIT_CODES = {300031, 300012}
_DETAIL_GONE_CODES = {300011}


def _detail_error_kind(raw_payload: dict[str, Any]) -> str:
    """Machine-readable reason: ``rate_limited`` | ``gone`` | ``empty``."""
    code = raw_payload.get("code")
    if code in _DETAIL_RATE_LIMIT_CODES:
        return "rate_limited"
    if code in _DETAIL_GONE_CODES:
        return "gone"
    return "empty"


def _detail_error_status(raw_payload: dict[str, Any]) -> int:
    """429 for throttle (retryable), 404 for a dead note, 502 otherwise."""
    kind = _detail_error_kind(raw_payload)
    if kind == "rate_limited":
        return status.HTTP_429_TOO_MANY_REQUESTS
    if kind == "gone":
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_502_BAD_GATEWAY


def _detail_business_error(raw_payload: dict[str, Any]) -> str:
    """Return a human message when the payload carries no usable note data."""
    code = raw_payload.get("code")
    msg = str(raw_payload.get("msg") or "").strip()
    data = raw_payload.get("data") or {}
    items = data.get("items") if isinstance(data, dict) else None
    has_item = bool(items) and isinstance(items, list) and bool(items[0])
    if has_item:
        return ""
    if code in (300031, 300011, 300012):
        return f"这篇笔记暂时无法浏览（{msg or '可能已删除、设为私密或被限流'}）"
    if code not in (None, 0, -1) and not has_item:
        return f"笔记详情读取失败：{msg or f'业务码 {code}'}"
    if not has_item:
        return "笔记详情为空，可能已删除、设为私密，或当前账号无权限查看"
    return ""


@router.post("/notes/comments")
def note_comments(
    payload: NoteCommentsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    cookies = _resolve_cookies(db, current_user, payload.account_id)
    success, message, raw_payload = adapter_factory(cookies).get_note_comments(payload.note_url)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=message or "XHS note comments failed",
        )
    items = normalize_comment_payload(raw_payload)
    saved_note_id, saved = _persist_comments(db, current_user, payload.note_url, items)
    return {
        "total": len(items),
        "items": items,
        "saved": saved,
        "note_db_id": saved_note_id,
    }


def _persist_comments(
    db: Session,
    current_user: User,
    note_url: str,
    items: list[dict[str, Any]],
) -> tuple[int | None, int]:
    """Write fetched comments into ``note_comments`` so insights can read them.

    The adapter only fetches; without this step the analytics page would keep
    showing zero comments even after a successful crawl.
    """
    if not items:
        return None, 0

    note_id = ""
    # Real XHS note ids are 24-hex strings; a naive /explore/<word> match would
    # truncate slugs such as "comment-persist-001" to "comment".
    for pattern in (
        r"/explore/([0-9a-fA-F]{16,32})",
        r"/(?:discovery/item|item|note)/([0-9a-fA-F]{16,32})",
    ):
        match = re.search(pattern, note_url or "")
        if match:
            note_id = match.group(1)
            break
    if not note_id:
        bare = (note_url or "").strip().split("?")[0].rstrip("/").split("/")[-1]
        if re.fullmatch(r"[0-9a-fA-F]{16,32}", bare):
            note_id = bare
    if not note_id:
        return None, 0

    note = (
        db.query(Note)
        .filter(
            Note.user_id == current_user.id,
            Note.platform == "xhs",
            Note.note_id == note_id,
        )
        .first()
    )
    if note is None:
        return None, 0

    existing = {
        row.comment_id: row
        for row in db.query(NoteComment).filter(NoteComment.note_id == note.id).all()
    }
    saved = 0
    for item in items:
        comment_id = str(item.get("comment_id") or "").strip()
        if not comment_id:
            continue
        row = existing.get(comment_id)
        if row is None:
            row = NoteComment(note_id=note.id, comment_id=comment_id)
            db.add(row)
        row.user_name = str(item.get("user_name") or "")
        row.user_id = str(item.get("user_id") or "")
        row.content = str(item.get("content") or "")
        row.like_count = int(item.get("like_count") or 0)
        row.parent_comment_id = str(item.get("parent_comment_id") or "")
        row.created_at_remote = str(item.get("created_at_remote") or "")
        row.raw_json = item.get("raw_json") or {}
        saved += 1
    if saved:
        db.commit()
    return note.id, saved
