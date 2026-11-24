"""P2-25：样本库 1000 条上限已经不在了 —— 前端按 total 翻页。

这条是前端改动（`lib/corpus.ts`），后端没有对应测试。这里只钉住
「后端 total 与按页拼接结果一致」这个前提，防止将来后端把 total 改成
「本页条数」而前端还在按 total 循环（会变成只拉一页）。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api import notes as notes_api
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import Note, PlatformAccount, User


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'page.db'}", connect_args={"check_same_thread": False}
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
    for i in range(230):
        db.add(
            Note(
                user_id=user.id,
                platform="xhs",
                platform_account_id=account.id,
                note_id=f"n{i:04d}",
                title=f"t{i}",
                content="正文",
                source_type="discovery",
            )
        )
    db.commit()

    app = FastAPI()
    app.include_router(notes_api.router, prefix="/api")

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


def test_total_describes_the_whole_result_set_not_the_page(client):
    """前端按 `out.length >= total` 判停；total 一旦变成「本页条数」就会少拉。"""
    first = client.get("/api/notes?page=1&page_size=100").json()
    assert first["total"] == 230
    assert len(first["items"]) == 100

    second = client.get("/api/notes?page=2&page_size=100").json()
    assert second["total"] == 230, "total 必须在每一页都一样"
    assert len(second["items"]) == 100

    third = client.get("/api/notes?page=3&page_size=100").json()
    assert third["total"] == 230
    assert len(third["items"]) == 30


def test_paging_reaches_every_row_exactly_once(client):
    """按 total 翻到底能覆盖全部行，且不重复 —— 对应 loadAllNotes 的循环。"""
    seen: list[str] = []
    page = 1
    while page <= 50:
        payload = client.get(f"/api/notes?page={page}&page_size=100").json()
        items = payload["items"]
        if not items:
            break
        seen.extend(n["note_id"] for n in items)
        if len(items) < 100 or len(seen) >= payload["total"]:
            break
        page += 1

    assert len(seen) == 230
    assert len(set(seen)) == 230, "翻页产生了重复行"
