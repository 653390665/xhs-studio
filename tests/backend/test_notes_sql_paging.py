"""P2-5：notes 列表已改为 SQL 分页。钉住三件事。

1. `page_size=1` 的 SQL 数应远低于 `page_size=100`（原实现两者相同）。
2. `total` 仍是全量（不是本页条数）。
3. 分页边界：最后一页、越界页、page_size 上限。

2026-11-18 实测（704 行）：
  改前  page_size=1 593ms / =100 593ms / 1,409 条 SQL
  改后  page_size=1  37ms / =100  93ms / 主要开销随当页行数变化
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.app.api import notes as notes_api
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import Note, NoteAsset, PlatformAccount, Tag, User, note_tags


@pytest.fixture()
def ctx(tmp_path):
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

    tag = Tag(user_id=user.id, name="t")
    db.add(tag)
    db.commit()
    db.refresh(tag)

    for i in range(230):
        note = Note(
            user_id=user.id,
            platform="xhs",
            platform_account_id=account.id,
            note_id=f"n{i:04d}",
            title=f"t{i}",
            content="正文",
            source_type="discovery",
        )
        db.add(note)
        db.flush()
        db.add(
            NoteAsset(
                note_id=note.id,
                asset_type="image",
                url=f"https://cdn.test/{i}.webp",
                local_path="",
                sort_order=0,
            )
        )
        db.execute(note_tags.insert().values(note_id=note.id, tag_id=tag.id))
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

    counter = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    with TestClient(app) as c:
        yield c, counter
    db.close()


def test_small_page_issues_fewer_queries_than_big_page(ctx):
    c, counter = ctx

    counter["n"] = 0
    c.get("/api/notes?page_size=1")
    one = counter["n"]

    counter["n"] = 0
    c.get("/api/notes?page_size=100")
    hundred = counter["n"]

    assert hundred > one * 5, (
        f"page_size=1 用了 {one} 条 SQL、=100 用了 {hundred} 条——"
        "差距太小说明还在全量序列化"
    )


def test_total_is_still_the_whole_set(ctx):
    c, _ = ctx
    payload = c.get("/api/notes?page_size=20").json()
    assert payload["total"] == 230
    assert len(payload["items"]) == 20


def test_last_page_and_out_of_range(ctx):
    c, _ = ctx
    last = c.get("/api/notes?page=3&page_size=100").json()
    assert len(last["items"]) == 30
    assert last["total"] == 230

    beyond = c.get("/api/notes?page=99&page_size=100").json()
    assert beyond["items"] == []
    assert beyond["total"] == 230, "越界页的 total 仍是全量"


def test_page_size_cap_is_100(ctx):
    c, _ = ctx
    assert c.get("/api/notes?page_size=101").status_code == 422
    ok = c.get("/api/notes?page_size=100").json()
    assert len(ok["items"]) == 100


def test_tags_and_cover_survive_sql_paging(ctx):
    """分页改了取数方式，tags / cover 这些 N+1 字段不能丢。"""
    c, _ = ctx
    items = c.get("/api/notes?page_size=5").json()["items"]
    assert len(items) == 5
    for note in items:
        assert note["tags"], "tags 丢了"
        assert note["cover_url"].startswith("https://cdn.test/"), note["cover_url"]
