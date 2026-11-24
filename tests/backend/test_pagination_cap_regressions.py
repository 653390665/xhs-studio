"""分页上限：publish 与 tags 必须能返回自己声明的行数。

两条都是 2026-11-18 实测出来的：

* ``/api/publish/jobs`` 声明 ``le=500``，队列也请求 500，但共享分页器硬截 100。
  130 条待确认时只有 100 行可见，第 101 条起点不到、也发不了，而 counts 仍说 130。
* ``/api/tags`` 活库有 151 个，前端只拿 100 个 —— 高频话题（38/35/34 篇）
  永远进不了 chip，而「另有 N 个」少报 51 个。

修法是给 ``paginated()`` 加显式 ``max_size``，由需要更大页的路由自己声明，
默认仍是 100，避免所有列表一起放宽。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api import publish as publish_api
from backend.app.api import tags as tags_api
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import PlatformAccount, PublishJob, Tag, User
from backend.app.schemas.common import paginated


# ---------------------------------------------------------------- 分页器本身


def test_max_size_widens_the_cap_for_one_caller():
    out = paginated(list(range(300)), page=1, page_size=500, max_size=500)
    assert out["total"] == 300
    assert len(out["items"]) == 300, "声明 500 却只给 100 条，调用方无法察觉"


def test_default_cap_stays_at_100():
    """不传 max_size 时仍按 100 截，避免所有列表一起放大响应。"""
    out = paginated(list(range(300)), page=1, page_size=200)
    assert len(out["items"]) == 100


def test_max_size_still_bounds_the_page_size():
    out = paginated(list(range(600)), page=1, page_size=600, max_size=500)
    assert len(out["items"]) == 500


# ---------------------------------------------------------------- 两条真实路由


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'p.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="a", status="active"
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    for i in range(130):
        db.add(
            PublishJob(
                user_id=user.id,
                platform_account_id=account.id,
                platform="xhs",
                title=f"job-{i}",
                body="",
                publish_mode="immediate",
                publish_options="{}",
                status="pending",
            )
        )
    # 151 个 tag：超过前端原先能拿到的 100
    for i in range(151):
        db.add(Tag(user_id=user.id, name=f"tag-{i:03d}"))
    db.commit()

    app = FastAPI()
    app.include_router(publish_api.router, prefix="/api")
    app.include_router(tags_api.router, prefix="/api")

    def _db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c
    db.close()


def test_publish_jobs_returns_every_row_it_counts(client):
    response = client.get("/api/publish/jobs?page_size=500")
    assert response.status_code == 200
    payload = response.json()

    counts = payload.get("counts") or {}
    items = payload.get("items") or []

    assert payload["total"] == 130
    assert len(items) == 130, (
        f"counts.pending={counts.get('pending')} 但只返回 {len(items)} 行——"
        "第 101 条起在队列里点不到"
    )
    assert counts.get("pending") == len(items)


def test_tags_list_can_return_all_tags(client):
    response = client.get("/api/tags?page_size=500")
    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] == 151
    assert len(payload["items"]) == 151, (
        "只返回 100 个：高频话题进不了前 12 个 chip，剩余数也少报"
    )


def test_tags_page_size_cap_is_500_not_100(client):
    """路由声明 le=500；传 600 应 422，而不是静默截到 100。"""
    assert client.get("/api/tags?page_size=600").status_code == 422
