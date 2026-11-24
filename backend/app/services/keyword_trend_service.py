"""Compute keyword trends from daily hit snapshots.

Before this module the keywords page only did a live string match against the
library, so it could answer "how many samples mention this word" but never "is
this word rising". We now record one row per (user, keyword, day) whenever the
page is opened, and derive a delta against the previous snapshot.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import shanghai_now
from backend.app.models import KeywordHitSnapshot, User


def today_key() -> str:
    return shanghai_now().strftime("%Y-%m-%d")


def record_keyword_hits(
    db: Session,
    user: User,
    items: list[dict[str, Any]],
) -> None:
    """Upsert today's hit counts for each keyword.

    Called on every keywords-page load, so the same day is overwritten rather
    than appended, keeping one row per day.
    """
    if not items:
        return
    day = today_key()
    existing = {
        row.keyword: row
        for row in db.scalars(
            select(KeywordHitSnapshot).where(
                KeywordHitSnapshot.user_id == user.id,
                KeywordHitSnapshot.snapshot_date == day,
            )
        ).all()
    }
    changed = False
    for item in items:
        keyword = str(item.get("keyword") or "").strip()
        if not keyword:
            continue
        row = existing.get(keyword)
        if row is None:
            row = KeywordHitSnapshot(
                user_id=user.id,
                keyword=keyword,
                snapshot_date=day,
            )
            db.add(row)
            existing[keyword] = row
        row.group_name = str(item.get("group_name") or "")
        row.notes = int(item.get("notes") or 0)
        row.engagement = int(item.get("engagement") or 0)
        changed = True
    if changed:
        db.commit()


def attach_trends(
    db: Session,
    user: User,
    items: list[dict[str, Any]],
    *,
    lookback_days: int = 7,
) -> list[dict[str, Any]]:
    """Attach previous counts and a delta to each keyword row."""
    if not items:
        return items
    day = today_key()
    since = (shanghai_now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    rows = db.scalars(
        select(KeywordHitSnapshot)
        .where(
            KeywordHitSnapshot.user_id == user.id,
            KeywordHitSnapshot.snapshot_date >= since,
            KeywordHitSnapshot.snapshot_date < day,
        )
        .order_by(KeywordHitSnapshot.snapshot_date.asc())
    ).all()

    history: dict[str, list[KeywordHitSnapshot]] = {}
    for row in rows:
        history.setdefault(row.keyword, []).append(row)

    enriched: list[dict[str, Any]] = []
    for item in items:
        keyword = str(item.get("keyword") or "")
        past = history.get(keyword) or []
        if not past:
            enriched.append(
                {
                    **item,
                    "previous_notes": None,
                    "previous_engagement": None,
                    "notes_delta": None,
                    "engagement_delta": None,
                    "trend": "new",
                    "last_seen": "",
                }
            )
            continue
        prev = past[-1]
        notes_delta = int(item.get("notes") or 0) - int(prev.notes or 0)
        engagement_delta = int(item.get("engagement") or 0) - int(prev.engagement or 0)
        if notes_delta > 0:
            trend = "up"
        elif notes_delta < 0:
            trend = "down"
        else:
            trend = "flat"
        enriched.append(
            {
                **item,
                "previous_notes": int(prev.notes or 0),
                "previous_engagement": int(prev.engagement or 0),
                "notes_delta": notes_delta,
                "engagement_delta": engagement_delta,
                "trend": trend,
                "last_seen": prev.snapshot_date,
            }
        )
    return enriched


def snapshot_history(
    db: Session,
    user: User,
    keyword: str,
    *,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Return the daily series for one keyword (oldest first)."""
    since = (shanghai_now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.scalars(
        select(KeywordHitSnapshot)
        .where(
            KeywordHitSnapshot.user_id == user.id,
            KeywordHitSnapshot.keyword == keyword,
            KeywordHitSnapshot.snapshot_date >= since,
        )
        .order_by(KeywordHitSnapshot.snapshot_date.asc())
    ).all()
    return [
        {
            "date": row.snapshot_date,
            "notes": int(row.notes or 0),
            "engagement": int(row.engagement or 0),
        }
        for row in rows
    ]
