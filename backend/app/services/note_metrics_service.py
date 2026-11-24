from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any

from backend.app.core.time import SHANGHAI_TZ, shanghai_now


def parse_count(value: Any) -> int:
    """Parse XHS counters that may be returned as ints or Chinese-style strings."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "").replace("+", "")
    if not text:
        return 0
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    elif text.lower().endswith("w"):
        multiplier = 10000
        text = text[:-1]
    elif text.lower().endswith("k"):
        multiplier = 1000
        text = text[:-1]
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0
    return int(float(match.group(0)) * multiplier)


def compute_note_metrics(
    likes: int,
    collects: int,
    comments: int,
    shares: int,
    fans: int,
) -> dict[str, float]:
    likes = max(0, int(likes or 0))
    collects = max(0, int(collects or 0))
    comments = max(0, int(comments or 0))
    shares = max(0, int(shares or 0))
    fans = max(0, int(fans or 0))
    if fans <= 0:
        return {"like_fan_ratio": 0.0, "engagement_rate": 0.0}
    engagement = likes + collects + comments + shares
    return {
        "like_fan_ratio": round(likes / fans, 4),
        "engagement_rate": round(engagement / fans, 4),
    }


def _first_metric(raw: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in raw and raw.get(key) is not None:
            return parse_count(raw.get(key))
    return 0


def parse_published_at(value: Any) -> datetime | None:
    """Normalize a platform timestamp into naive Asia/Shanghai wall-clock time.

    Three shapes arrive in practice:

    * seconds — ``1730184000``
    * milliseconds — ``1730184000000`` (RedFox and some web payloads)
    * text — ``2026-11-04 20:08`` / ``2026-11-04``

    Anything else returns ``None``, which means "unknown". It must not default to
    "now": a note whose date we failed to read would otherwise pass every
    "posted in the last 7 days" filter and quietly inflate the breakout list.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        stamp = int(value)
        if stamp <= 0:
            return None
        if stamp > 10**11:  # milliseconds
            stamp //= 1000
        try:
            return datetime.fromtimestamp(stamp, SHANGHAI_TZ).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return parse_published_at(int(text))
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%Y年%m月%d日",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def extract_note_metrics(raw: Any) -> dict[str, Any]:
    """Extract author id and engagement counters from search/detail raw payloads."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}

    card: dict[str, Any] = {}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    # Two payload shapes exist for the same web endpoint: the search wrapper
    # nests the card under ``data.items[0]``, while the note-detail wrapper puts
    # ``items[0]`` at the top level. Only reading the former silently dropped
    # the publish time (and the cover/engagement fields) of every detail
    # capture — 109 rows in the live database.
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if not items and isinstance(raw.get("items"), list):
        items = raw["items"]
    if items and isinstance(items[0], dict):
        item = items[0]
        card = item.get("note_card") if isinstance(item.get("note_card"), dict) else item
    elif isinstance(raw.get("note_card"), dict):
        card = raw["note_card"]

    interact = card.get("interact_info") if isinstance(card.get("interact_info"), dict) else {}
    merged = {**raw, **card, **interact}
    author = card.get("user") if isinstance(card.get("user"), dict) else {}
    if not author and isinstance(raw.get("user"), dict):
        author = raw["user"]

    return {
        "author_id": str(author.get("user_id") or author.get("id") or raw.get("author_id") or ""),
        "author_name": str(author.get("nickname") or author.get("name") or raw.get("author_name") or ""),
        "likes": _first_metric(merged, ("likes", "liked_count", "like_count", "likedCount")),
        "collects": _first_metric(merged, ("collects", "collected_count", "collect_count", "collectedCount")),
        "comments": _first_metric(merged, ("comments", "comment_count", "commentCount")),
        "shares": _first_metric(merged, ("shares", "share_count", "shareCount")),
        # Publication time, not crawl time. Three shapes appear: ``time`` in the
        # web card (seconds), ``workPublishTime`` in RedFox (ms or text), and
        # ``published_at`` in Douyin extraction payloads (date or text).
        "published_at": parse_published_at(
            card.get("time")
            or card.get("create_time")
            or merged.get("published_at")
            or merged.get("workPublishTime")
            or merged.get("time")
            or raw.get("time")
        ),
    }


def normalize_author_profile(payload: Any) -> dict[str, Any]:
    """Normalize /api/sns/web/v1/user/otherinfo payload into a compact profile.

    XHS returns follower stats in a ``data.interactions`` list
    (``type`` = follows / fans / interaction), not in ``basic_info``.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}
    basic = data.get("basic_info") if isinstance(data.get("basic_info"), dict) else data

    stats: dict[str, int] = {}
    interactions = data.get("interactions")
    if isinstance(interactions, list):
        for item in interactions:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or "")
            name = str(item.get("name") or "")
            count = parse_count(item.get("count") or item.get("i18n_count"))
            if kind == "fans" or "粉丝" in name:
                stats["fans"] = count
            elif kind == "follows" or "关注" in name:
                stats["follows"] = count
            elif kind == "interaction" or "获赞" in name:
                stats["interactions"] = count

    return {
        "user_id": str(basic.get("user_id") or basic.get("id") or ""),
        "nickname": str(basic.get("nickname") or basic.get("name") or ""),
        "fans": stats.get(
            "fans", parse_count(basic.get("fans") or basic.get("fans_count") or basic.get("fansCount"))
        ),
        "follows": stats.get(
            "follows", parse_count(basic.get("follows") or basic.get("follows_count"))
        ),
        "notes": parse_count(
            data.get("posted") or basic.get("note_num") or basic.get("note_count") or basic.get("notes")
        ),
        "interactions": stats.get("interactions", parse_count(data.get("liked"))),
    }


def apply_author_profile(item: dict[str, Any], profile: dict[str, Any] | None) -> None:
    """Attach author fans and derived rates to a normalized search item."""
    metrics = extract_note_metrics(item.get("raw"))
    likes = int(item.get("likes") or metrics.get("likes") or 0)
    collects = int(item.get("collects") or metrics.get("collects") or 0)
    comments = int(item.get("comments") or metrics.get("comments") or 0)
    shares = int(item.get("shares") or metrics.get("shares") or 0)

    if profile:
        item["author_fans"] = int(profile.get("fans") or 0)
        if not item.get("author_name"):
            item["author_name"] = profile.get("nickname") or ""
        item["author_follows"] = int(profile.get("follows") or 0)
        item["author_notes"] = int(profile.get("notes") or 0)
        item["like_fan_ratio"], item["engagement_rate"] = _values(
            likes, collects, comments, shares, item["author_fans"]
        )
        item["metrics_fetched_at"] = shanghai_now().isoformat()
        item.pop("metrics_error", None)
    else:
        item.setdefault("author_fans", 0)
        item.setdefault("like_fan_ratio", 0.0)
        item.setdefault("engagement_rate", 0.0)
        item["metrics_error"] = "author profile unavailable"


def _values(likes: int, collects: int, comments: int, shares: int, fans: int) -> tuple[float, float]:
    rates = compute_note_metrics(likes, collects, comments, shares, fans)
    return rates["like_fan_ratio"], rates["engagement_rate"]


def enrich_items_with_authors(
    adapter: Any,
    items: list[dict[str, Any]],
    *,
    min_likes_for_profile: int = 0,
    max_profiles: int = 10,
    sleep_seconds: float = 0.35,
    cache: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, int]:
    """Fetch author follower counts for candidate notes, in-place.

    Only notes reaching ``min_likes_for_profile`` are considered, each author is
    requested at most once per call, and at most ``max_profiles`` new profiles
    are fetched to keep the extra request volume bounded.
    """
    cache = cache if cache is not None else {}
    for item in items:
        item.setdefault("author_fans", 0)
    author_ids: list[str] = []
    for item in items:
        author_id = str(item.get("author_id") or "")
        likes = int(item.get("likes") or 0)
        if not author_id or likes < min_likes_for_profile:
            continue
        if author_id not in author_ids:
            author_ids.append(author_id)

    requested = 0
    fetched = 0
    errors = 0
    for author_id in author_ids:
        if author_id not in cache:
            if requested >= max(0, max_profiles):
                continue
            requested += 1
            success, _message, payload = adapter.get_user_info(author_id)
            profile = normalize_author_profile(payload) if success else None
            cache[author_id] = profile or None
            if profile:
                fetched += 1
            else:
                errors += 1
            if sleep_seconds > 0 and requested < max_profiles:
                time.sleep(sleep_seconds)

        profile = cache.get(author_id)
        for item in items:
            if str(item.get("author_id") or "") == author_id:
                apply_author_profile(item, profile)

    return {
        "candidate_authors": len(author_ids),
        "profiles_requested": requested,
        "profiles_fetched": fetched,
        "profile_errors": errors,
        "profiles_cached": sum(1 for value in cache.values() if value),
    }


def filter_and_sort_items(
    items: list[dict[str, Any]],
    *,
    max_fans: int = 0,
    min_likes: int = 0,
    min_like_fan_ratio: float = 0.0,
    within_days: int = 0,
    sort_by: str = "default",
) -> list[dict[str, Any]]:
    filtered = []
    for item in items:
        likes = int(item.get("likes") or 0)
        fans = int(item.get("author_fans") or 0)
        ratio = float(item.get("like_fan_ratio") or 0.0)
        if min_likes > 0 and likes < min_likes:
            continue
        if max_fans > 0 and not (0 < fans <= max_fans):
            continue
        if min_like_fan_ratio > 0 and ratio < min_like_fan_ratio:
            continue
        if within_days > 0:
            # Unknown age fails the window rather than passing it. A note whose
            # date we could not parse is not evidence of recency.
            days = _days_old(item.get("published_at"))
            if days is None or days > within_days:
                continue
        filtered.append(item)

    sort_keys = {
        "likes": lambda item: int(item.get("likes") or 0),
        "like_fan_ratio": lambda item: float(item.get("like_fan_ratio") or 0.0),
        "engagement_rate": lambda item: float(item.get("engagement_rate") or 0.0),
    }
    if sort_by in sort_keys:
        filtered.sort(key=sort_keys[sort_by], reverse=True)
    return filtered


def _days_old(value: Any) -> int | None:
    """Whole days since publication, or None when the date is unknown."""
    from datetime import date, datetime

    if isinstance(value, datetime):
        published = value.date()
    elif isinstance(value, date):
        published = value
    elif isinstance(value, str) and value.strip():
        from backend.app.services.note_metrics_service import parse_published_at

        parsed = parse_published_at(value)
        if parsed is None:
            return None
        published = parsed.date()
    else:
        return None
    return max(0, (shanghai_now().date() - published).days)
