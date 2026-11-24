"""Free Xiaohongshu hot-search source (60s API).

RedFox's hot list costs ~¥0.06 per call and stops working when the account runs
out of points. This module provides a **free** fallback that returns the same
shape, so the 热榜 tab keeps working without any key or balance.

Upstream: ``GET https://60s.viki.moe/v2/rednote`` →
``{"code":200,"data":[{rank,title,score,word_type,work_type_icon,link}, ...]}``

The response is cached briefly to avoid hammering a free public service.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from backend.app.core.config import get_settings
from backend.app.services.note_metrics_service import parse_count

CACHE_TTL_SECONDS = 300
FAILURE_BACKOFF_SECONDS = 120

_lock = threading.Lock()
_cache: dict[str, Any] = {
    "checked_at": 0.0,
    "payload": None,
    "failure_at": 0.0,
    "failure_reason": "",
}


def reset_free_hot_search_cache() -> None:
    """Testing / manual helper: forget the cached hot list and backoff."""
    with _lock:
        _cache["checked_at"] = 0.0
        _cache["payload"] = None
        _cache["failure_at"] = 0.0
        _cache["failure_reason"] = ""


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    score = item.get("score")
    return {
        "rank": parse_count(item.get("rank")),
        "title": str(item.get("title") or "").strip(),
        "hot_score": parse_count(score),
        "hot_text": str(score or ""),
        "url": str(item.get("link") or ""),
        "word_type": str(item.get("word_type") or ""),
        "updated_at": "",
    }


def _remember_failure(
    reason: str,
    now: float,
    cached: dict[str, Any] | None,
) -> tuple[bool, str, dict[str, Any] | None]:
    with _lock:
        _cache["failure_at"] = now
        _cache["failure_reason"] = reason
    if cached is not None:
        return True, f"{reason}（使用上次缓存）", {**cached, "stale": True}
    return False, reason, None


def fetch_free_hot_list(*, refresh: bool = False) -> tuple[bool, str, dict[str, Any] | None]:
    """Return ``(success, message, {"items", "total", "source"})``."""
    settings = get_settings()
    if not settings.free_hot_search_enabled:
        return False, "免费热搜源已在配置中关闭。", None

    now = time.monotonic()
    with _lock:
        cached = _cache["payload"]
        checked_at = _cache["checked_at"]
        failure_at = _cache["failure_at"]
        failure_reason = _cache["failure_reason"]
    if not refresh and cached is not None and now - checked_at < CACHE_TTL_SECONDS:
        return True, "ok", dict(cached)

    if not refresh and failure_at and now - failure_at < FAILURE_BACKOFF_SECONDS:
        if cached is not None:
            return True, "热搜源暂时限流，使用上次缓存。", {**cached, "stale": True}
        return False, failure_reason or "免费热搜源暂时不可用。", None

    url = f"{settings.free_hot_search_base_url.rstrip('/')}{settings.free_hot_search_path}"
    try:
        response = httpx.get(url, timeout=settings.free_hot_search_timeout_seconds)
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as error:
        status_code = error.response.status_code if error.response is not None else 0
        reason = (
            "免费热搜源限流（429），已暂停请求，稍后再试。"
            if status_code == 429
            else f"免费热搜源请求失败：HTTP {status_code}"
        )
        return _remember_failure(reason, now, cached)
    except Exception as error:  # noqa: BLE001 - any network/JSON problem means "unavailable"
        reason = f"免费热搜源请求失败：{type(error).__name__}"
        return _remember_failure(reason, now, cached)

    if not isinstance(body, dict):
        return False, "免费热搜源返回格式异常。", None
    code = body.get("code")
    if code not in (200, "200", None):
        return False, f"免费热搜源返回异常 code={code}", None

    raw_items = body.get("data")
    items = [_normalize(item) for item in raw_items] if isinstance(raw_items, list) else []
    items = [item for item in items if item["title"]]
    items.sort(key=lambda row: row["rank"])

    payload = {
        "items": items,
        "total": len(items),
        "source": "free",
        "provider": "60s",
    }
    with _lock:
        _cache["checked_at"] = time.monotonic()
        _cache["payload"] = payload
        _cache["failure_at"] = 0.0
        _cache["failure_reason"] = ""
    return True, "ok", payload
