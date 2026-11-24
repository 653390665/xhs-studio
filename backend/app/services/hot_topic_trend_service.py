"""Daily hot-topic snapshots and trend deltas.

Every hot-list fetch records one row per topic per day (unique constraint), so a
topic's trajectory can be derived later: rising / falling / flat / new.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import shanghai_now
from backend.app.models import HotTopicSnapshot

DEFAULT_TREND_DAYS = 7
FLAT_THRESHOLD_PCT = 3.0


def record_snapshot(
    db: Session, items: list[dict[str, Any]], source: str = "free"
) -> int:
    """Insert/update today's snapshot rows. Returns the number of rows touched."""
    today = shanghai_now().strftime("%Y-%m-%d")
    if not items:
        return 0

    titles = [str(item.get("title") or "") for item in items if item.get("title")]
    if not titles:
        return 0

    existing = {
        row.title: row
        for row in db.scalars(
            select(HotTopicSnapshot).where(
                HotTopicSnapshot.snapshot_date == today,
                HotTopicSnapshot.title.in_(titles),
            )
        ).all()
    }

    touched = 0
    captured_at = shanghai_now()
    for item in items:
        title = str(item.get("title") or "")
        if not title:
            continue
        hot_score = int(item.get("hot_score") or 0)
        rank = int(item.get("rank") or item.get("index") or 0)
        hot_text = str(item.get("hot_text") or "")
        row = existing.get(title)
        if row is None:
            db.add(
                HotTopicSnapshot(
                    title=title,
                    snapshot_date=today,
                    hot_score=hot_score,
                    hot_text=hot_text,
                    rank=rank,
                    source=source,
                    captured_at=captured_at,
                )
            )
        else:
            row.hot_score = hot_score
            row.hot_text = hot_text
            row.rank = rank
            row.source = source
            row.captured_at = captured_at
        touched += 1

    db.commit()
    return touched


def _trend_payload(rows: list[HotTopicSnapshot]) -> dict[str, Any]:
    points = [row.hot_score for row in rows]
    if len(rows) < 2:
        return {
            "direction": "new",
            "delta_pct": 0.0,
            "points": points,
            "days": len(rows),
            "first_text": rows[0].hot_text if rows else "",
            "last_text": rows[-1].hot_text if rows else "",
        }
    first, last = rows[0], rows[-1]
    delta = (last.hot_score - first.hot_score) / max(first.hot_score, 1) * 100
    if delta >= FLAT_THRESHOLD_PCT:
        direction = "up"
    elif delta <= -FLAT_THRESHOLD_PCT:
        direction = "down"
    else:
        direction = "flat"
    return {
        "direction": direction,
        "delta_pct": round(delta, 1),
        "points": points,
        "days": len(rows),
        "first_text": first.hot_text,
        "last_text": last.hot_text,
    }


def attach_trends(
    db: Session, items: list[dict[str, Any]], days: int = DEFAULT_TREND_DAYS
) -> list[dict[str, Any]]:
    """Annotate items with ``trend`` = {direction, delta_pct, points, days}.

    Items whose title has fewer than one stored snapshot get ``direction="new"``.
    """
    titles = [str(item.get("title") or "") for item in items if item.get("title")]
    if not titles:
        return items

    cutoff = (shanghai_now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    rows = db.scalars(
        select(HotTopicSnapshot)
        .where(
            HotTopicSnapshot.title.in_(titles),
            HotTopicSnapshot.snapshot_date >= cutoff,
        )
        .order_by(HotTopicSnapshot.snapshot_date.asc())
    ).all()

    by_title: dict[str, list[HotTopicSnapshot]] = {}
    for row in rows:
        by_title.setdefault(row.title, []).append(row)

    for item in items:
        title = str(item.get("title") or "")
        item["trend"] = _trend_payload(by_title.get(title, []))
    return items


def topic_series(db: Session, title: str, days: int = 30) -> dict[str, Any]:
    """Full daily series for one topic (for a sparkline/detail view)."""
    cutoff = (shanghai_now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    rows = db.scalars(
        select(HotTopicSnapshot)
        .where(HotTopicSnapshot.title == title, HotTopicSnapshot.snapshot_date >= cutoff)
        .order_by(HotTopicSnapshot.snapshot_date.asc())
    ).all()
    return {
        "title": title,
        "points": [
            {"date": row.snapshot_date, "hot_score": row.hot_score, "hot_text": row.hot_text, "rank": row.rank}
            for row in rows
        ],
        "trend": _trend_payload(list(rows)),
    }


__all__ = [
    "DEFAULT_TREND_DAYS",
    "attach_trends",
    "record_snapshot",
    "topic_series",
]
