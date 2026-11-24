"""RedFox-only read endpoints: 爆款洞察 / 黑马爆文榜 / 每日·七日爆款榜单 / 搜索账号.

These features exist only in the RedFox Hub provider; the Spider_XHS PC SDK has no
equivalent data, so every endpoint here answers 400 when the effective provider is
``pc`` instead of silently returning nothing.

Nothing in this module writes to Xiaohongshu: all calls are read-only lookups.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.redfox_api_adapter import REDFOX_RANK_CATEGORIES, redfox_status
from backend.app.api.platforms.xhs.pc import (
    _normalize_search_item,
    get_xhs_redfox_adapter_factory,
)
from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User
from backend.app.services.free_hot_search_service import fetch_free_hot_list
from backend.app.services.hot_topic_trend_service import attach_trends, record_snapshot, topic_series
from backend.app.services.note_metrics_service import apply_author_profile

router = APIRouter(prefix="/xhs/trends", tags=["xhs-trends"])

_NO_KEY_MESSAGE = (
    "该功能的数据来自 RedFox 接口，需要配置 redfox_api_key（环境变量或 .env）。"
    "它与「笔记发现」使用的 PC 登录态互不影响，可同时启用。"
)


class ViralInsightsRequest(BaseModel):
    keyword: str = Field(default="", max_length=120)
    page_num: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)
    start_date: str = Field(default="", max_length=10)
    end_date: str = Field(default="", max_length=10)


class LowFanRankingRequest(BaseModel):
    category: str = Field(default="综合全部", max_length=40)
    rank_date: str = Field(default="", max_length=10)


class RankingRequest(BaseModel):
    period: str = Field(default="daily", pattern="^(daily|weekly)$")
    category: str = Field(default="综合全部", max_length=40)
    rank_date: str = Field(default="", max_length=10)


class SearchUsersRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=120)
    page: int = Field(default=1, ge=1)
    sort_type_choice: int = Field(default=0, ge=0, le=4)


class HotAccountsRequest(BaseModel):
    date_type: int = Field(default=1, ge=1, le=3)
    category: str = Field(default="综合全部", max_length=40)
    rank_date: str = Field(default="", max_length=10)


def _require_redfox() -> None:
    """Block RedFox-only endpoints with an actionable status code.

    400 = not configured at all, 402 = configured but out of points.
    """
    status_info = redfox_status()
    if status_info["available"]:
        return
    if status_info["reason"] == "insufficient_balance":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"{status_info['message']}（RedFox 模块已停用，其他功能正常）",
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=status_info["message"] or _NO_KEY_MESSAGE,
    )


def _normalize_trend_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize trend items into search-item shape and attach already-known metrics.

    Ranking/insight payloads ship the author's follower count, so no extra paid
    profile lookup is needed: we reuse ``apply_author_profile`` to derive the
    same ``author_fans`` / ``like_fan_ratio`` / ``engagement_rate`` keys the rest
    of the app expects.

    The provider's own ranking order is preserved (it already encodes that
    endpoint's meaning); the UI surfaces 赞粉比 separately instead of re-sorting,
    which would let a stray low-follower entry with an extreme ratio dominate.
    """
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        card = item.get("note_card") or {}
        entry = _normalize_search_item(item)
        if not entry.get("note_id"):
            continue
        fans = int(item.get("author_fans") or 0)
        profile = None
        if fans > 0:
            profile = {
                "fans": fans,
                "nickname": (card.get("user") or {}).get("nickname") or "",
                "notes": 0,
            }
        apply_author_profile(entry, profile)
        if item.get("interactive_count"):
            entry["interactive_count"] = int(item["interactive_count"])
        normalized.append(entry)
    return normalized


@router.get("/meta")
def trends_meta(
    refresh: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
):
    """Feature availability + the category list for the ranking selectors."""
    status_info = redfox_status(refresh=refresh)
    settings = get_settings()
    redfox_available = bool(status_info["available"])
    free_enabled = bool(settings.free_hot_search_enabled)
    hot_list_available = redfox_available or free_enabled
    if redfox_available:
        hot_list_source = "redfox"
    elif free_enabled:
        hot_list_source = "free"
    else:
        hot_list_source = "none"
    return {
        # these features are always served by RedFox, independently of the PC provider
        "provider": "redfox" if status_info["configured"] else "none",
        "available": redfox_available,
        "balance": status_info["balance"],
        "reason": status_info["reason"],
        "categories": list(REDFOX_RANK_CATEGORIES),
        "message": status_info["message"],
        # the hot list has a free fallback and stays usable without RedFox
        "hot_list_available": hot_list_available,
        "hot_list_source": hot_list_source,
        "features": {
            "viral_insights": redfox_available,
            "low_fan_ranking": redfox_available,
            "ranking": redfox_available,
            "hot_accounts": redfox_available,
            "search_users": redfox_available,
            "hot_list": hot_list_available,
        },
    }


@router.post("/viral-insights")
def viral_insights(
    payload: ViralInsightsRequest,
    current_user: User = Depends(get_current_user),
    adapter_factory=Depends(get_xhs_redfox_adapter_factory),
):
    """爆款笔记洞察：热门笔记 + 热门话题 + 相关搜索词."""
    _require_redfox()
    success, message, raw = adapter_factory("").search_viral_insights(
        payload.keyword,
        page_num=payload.page_num,
        page_size=payload.page_size,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "爆款洞察获取失败")

    data = (raw or {}).get("data") or {}
    items = _normalize_trend_items(data.get("items") or [])
    return {
        "items": items,
        "total": data.get("total") or len(items),
        "page_num": data.get("page_num") or payload.page_num,
        "page_size": data.get("page_size") or payload.page_size,
        "hot_topics": data.get("hot_topics") or [],
        "related_searches": data.get("related_searches") or [],
        "empty": not items,
    }


@router.post("/low-fan-ranking")
def low_fan_ranking(
    payload: LowFanRankingRequest,
    current_user: User = Depends(get_current_user),
    adapter_factory=Depends(get_xhs_redfox_adapter_factory),
):
    """小红书黑马爆文榜（低粉高互动）."""
    _require_redfox()
    success, message, raw = adapter_factory("").get_low_fan_ranking(payload.category, payload.rank_date)
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "黑马爆文榜获取失败")

    data = (raw or {}).get("data") or {}
    items = _normalize_trend_items(data.get("items") or [])
    return {
        "items": items,
        "total": data.get("total") or len(items),
        "category": data.get("category") or payload.category,
        # the adapter may fill in a default date, so echo what was actually used
        "rank_date": data.get("rank_date") or payload.rank_date,
        "empty": not items,
    }


@router.post("/ranking")
def ranking(
    payload: RankingRequest,
    current_user: User = Depends(get_current_user),
    adapter_factory=Depends(get_xhs_redfox_adapter_factory),
):
    """每日/七日爆款榜单."""
    _require_redfox()
    success, message, raw = adapter_factory("").get_ranking(
        payload.period, payload.rank_date, payload.category
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "爆款榜单获取失败")

    data = (raw or {}).get("data") or {}
    items = _normalize_trend_items(data.get("items") or [])
    return {
        "items": items,
        "total": data.get("total") or len(items),
        "period": payload.period,
        "category": data.get("category") or payload.category,
        "rank_date": data.get("rank_date") or payload.rank_date,
        "empty": not items,
    }


@router.get("/hot-list")
def hot_list(
    platform: int = Query(default=6, ge=1),
    start_date: str = Query(default="", max_length=10),
    end_date: str = Query(default="", max_length=10),
    refresh: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_redfox_adapter_factory),
):
    """各平台热点榜；默认 ``platform=6``（小红书）。

    RedFox is preferred. When it is unavailable (no key / no balance) the free
    60s source serves the Xiaohongshu list instead, so the tab keeps working.
    Every fetch records a daily snapshot so each topic gets a trend.
    """
    if platform == 6:
        status_info = redfox_status()
        if not status_info["available"]:
            success, message, payload = fetch_free_hot_list(refresh=refresh)
            if success:
                data = payload or {}
                items = data.get("items") or []
                record_snapshot(db, items, source="free")
                attach_trends(db, items)
                return {
                    "items": items,
                    "total": data.get("total") or 0,
                    "platform": 6,
                    "start_date": "",
                    "end_date": "",
                    "source": "free",
                    "provider": data.get("provider") or "60s",
                    "fallback_reason": status_info["reason"],
                    "empty": not items,
                }
            # Neither source worked: surface the RedFox reason, it explains more.
            if status_info["reason"] == "insufficient_balance":
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"{status_info['message']}（免费热搜源也不可用：{message}）",
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"RedFox 与免费热搜源均不可用：{message}",
            )

    _require_redfox()
    success, message, raw = adapter_factory("").get_platform_hot_list(
        platform=platform, start_date=start_date, end_date=end_date
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "热点榜获取失败")

    data = (raw or {}).get("data") or {}
    items = data.get("items") or []
    record_snapshot(db, items, source="redfox")
    attach_trends(db, items)
    return {
        "items": items,
        "total": data.get("total") or len(items),
        "platform": data.get("platform") or platform,
        "start_date": data.get("start_date") or start_date,
        "end_date": data.get("end_date") or end_date,
        "source": "redfox",
        "provider": "redfox",
        "empty": not items,
    }


@router.get("/topic-trend")
def hot_topic_trend(
    title: str = Query(min_length=1, max_length=256),
    days: int = Query(default=30, ge=1, le=180),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单个话题的热度时间序列（用于趋势图）。"""
    return topic_series(db, title, days=days)


@router.post("/search-users")
def search_users(
    payload: SearchUsersRequest,
    current_user: User = Depends(get_current_user),
    adapter_factory=Depends(get_xhs_redfox_adapter_factory),
):
    """按关键词搜索小红书账号（返回小红书号与粉丝数）."""
    _require_redfox()
    success, message, raw = adapter_factory("").search_users(
        payload.keyword, page=payload.page, sort_type_choice=payload.sort_type_choice
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "账号搜索失败")

    data = (raw or {}).get("data") or {}
    items = data.get("items") or []
    return {
        "items": items,
        "total": data.get("total") or len(items),
        "page": payload.page,
        "has_more": bool(data.get("has_more")),
        "empty": not items,
    }


@router.post("/hot-accounts")
def hot_accounts(
    payload: HotAccountsRequest,
    current_user: User = Depends(get_current_user),
    adapter_factory=Depends(get_xhs_redfox_adapter_factory),
):
    """小红书热门账号推荐（日/周/月榜，带涨粉、涨赞、涨藏）."""
    _require_redfox()
    success, message, raw = adapter_factory("").get_hot_accounts(
        date_type=payload.date_type,
        rank_date=payload.rank_date,
        category=payload.category,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "热门账号获取失败")

    data = (raw or {}).get("data") or {}
    items = data.get("items") or []
    return {
        "items": items,
        "total": data.get("total") or len(items),
        "date_type": data.get("date_type") or payload.date_type,
        "category": data.get("category") or payload.category,
        # the adapter fills a default date, so echo what was actually used
        "rank_date": data.get("rank_date") or payload.rank_date,
        "empty": not items,
    }
