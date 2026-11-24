"""库层面：低粉爆款筛选必须能在 SQL 里表达，并且排除「未知日期」。

前端筛选走 `/api/notes?low_follower=1&published_within_days=7`，
这里验证两件事：

1. ``low_follower=1`` 与 ``low_follower.DEFAULT_RULE`` 是同一套阈值；
2. 没有发布时间的笔记不会因为「比较结果是 unknown」而混进近期结果。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.models import Note, User
from backend.app.services.low_follower import DEFAULT_RULE


@pytest.fixture()
def client(tmp_path):
    from backend.app.api import notes as notes_api

    engine = create_engine(
        f"sqlite:///{tmp_path / 'notes.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()

    user = User(username="lf", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    now = shanghai_now()
    rows = [
        # 低粉爆款：183 粉 / 7325 赞 → 通过
        dict(note_id="hit", title="hit", author_fans=183, author_fans_status="known",
             like_count=7325, like_fan_ratio=40.0, published_at=now - timedelta(days=3)),
        # 大号同样赞 → 粉丝上限挡掉
        dict(note_id="big", title="big", author_fans=80000, author_fans_status="known",
             like_count=7325, like_fan_ratio=0.09, published_at=now - timedelta(days=3)),
        # 低粉但赞不够
        dict(note_id="quiet", title="quiet", author_fans=300, author_fans_status="known",
             like_count=100, like_fan_ratio=0.33, published_at=now - timedelta(days=3)),
        # 低粉爆款但太旧
        dict(note_id="old", title="old", author_fans=300, author_fans_status="known",
             like_count=6000, like_fan_ratio=20.0, published_at=now - timedelta(days=60)),
        # 低粉爆款但没有发布时间
        dict(note_id="undated", title="undated", author_fans=300, author_fans_status="known",
             like_count=6000, like_fan_ratio=20.0, published_at=None),
        # 粉丝数没采到
        dict(note_id="unknown", title="unknown", author_fans=0, author_fans_status="unknown",
             like_count=9000, like_fan_ratio=0.0, published_at=now - timedelta(days=3)),
    ]
    for row in rows:
        db.add(
            Note(
                user_id=user.id,
                platform_account_id=1,
                platform="xhs",
                source_type="discovery",
                **row,
            )
        )
    db.commit()

    app = FastAPI()
    app.include_router(notes_api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c, db
    db.close()


def _ids(response) -> set[str]:
    return {item["note_id"] for item in response.json()["items"]}


def test_low_follower_flag_uses_the_shared_thresholds(client):
    c, _ = client
    ids = _ids(c.get("/api/notes?low_follower=true"))
    assert ids == {"hit", "old", "undated"}, ids


def test_published_within_days_excludes_old_and_undated(client):
    c, _ = client
    ids = _ids(c.get("/api/notes?low_follower=true&published_within_days=7"))
    assert ids == {"hit"}, ids


def test_unknown_publication_date_never_counts_as_recent(client):
    c, _ = client
    ids = _ids(c.get("/api/notes?published_within_days=30"))
    assert "undated" not in ids


def test_thresholds_match_the_service_definition(client):
    c, _ = client
    body = c.get(f"/api/notes?low_follower=true&min_likes={DEFAULT_RULE.min_likes + 1}").json()
    ids = {item["note_id"] for item in body["items"]}
    assert ids == {"hit", "old", "undated"}


def test_serialized_note_exposes_published_at_and_fans_status(client):
    c, _ = client
    body = c.get("/api/notes?low_follower=true").json()
    item = next(i for i in body["items"] if i["note_id"] == "hit")
    assert item["published_at"]
    assert item["author_fans_status"] == "known"
    undated = next(i for i in body["items"] if i["note_id"] == "undated")
    assert undated["published_at"] is None
