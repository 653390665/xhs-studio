"""Tests for hot-topic snapshot recording and trend deltas."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now
from backend.app.models import HotTopicSnapshot
from backend.app.services import hot_topic_trend_service as svc


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_record_snapshot_is_daily_idempotent(db):
    items = [
        {"title": "话题A", "hot_score": 1000, "hot_text": "1000", "rank": 1},
        {"title": "话题B", "hot_score": 500, "hot_text": "500", "rank": 2},
    ]
    assert svc.record_snapshot(db, items, source="free") == 2

    # same day, updated values -> still one row per title
    items[0]["hot_score"] = 1200
    assert svc.record_snapshot(db, items, source="free") == 2

    rows = db.scalars(select(HotTopicSnapshot)).all()
    assert len(rows) == 2
    assert {row.title for row in rows} == {"话题A", "话题B"}
    row_a = next(row for row in rows if row.title == "话题A")
    assert row_a.hot_score == 1200


def _seed(db, title: str, scores: list[int]):
    today = shanghai_now()
    for index, score in enumerate(scores):
        day = (today - timedelta(days=len(scores) - 1 - index)).strftime("%Y-%m-%d")
        db.add(
            HotTopicSnapshot(
                title=title,
                snapshot_date=day,
                hot_score=score,
                hot_text=str(score),
                rank=1,
                source="free",
                captured_at=today,
            )
        )
    db.commit()


def test_attach_trends_directions(db):
    _seed(db, "上升话题", [100, 150])
    _seed(db, "下降话题", [200, 100])
    _seed(db, "平稳话题", [100, 101])

    items = [
        {"title": "上升话题"},
        {"title": "下降话题"},
        {"title": "平稳话题"},
        {"title": "新话题"},
    ]
    svc.attach_trends(db, items)
    by_title = {item["title"]: item["trend"] for item in items}

    assert by_title["上升话题"]["direction"] == "up"
    assert by_title["上升话题"]["delta_pct"] == 50.0
    assert by_title["上升话题"]["points"] == [100, 150]

    assert by_title["下降话题"]["direction"] == "down"
    assert by_title["下降话题"]["delta_pct"] == -50.0

    assert by_title["平稳话题"]["direction"] == "flat"
    assert by_title["新话题"]["direction"] == "new"
    assert by_title["新话题"]["days"] == 0


def test_topic_series(db):
    _seed(db, "序列话题", [10, 20, 40])

    data = svc.topic_series(db, "序列话题", days=7)

    assert data["title"] == "序列话题"
    assert len(data["points"]) == 3
    assert data["points"][-1]["hot_score"] == 40
    assert data["trend"]["direction"] == "up"
