"""P2-24：去重键必须和唯一索引一致。

唯一索引是 ``uq_notes_user_platform_note (user_id, platform, note_id)``，
而 batch-save 的查找条件是 ``(user_id, note_id)``——同一个 id 字符串出现在
另一个平台时，会被认成本平台的旧记录并原地改写，``platform`` 却不重写。

活库当前 0 碰撞（抖音全数字、小红书 24 位 hex），所以是潜在缺陷；
但抖音导入器把 work_id 当 note_id 写，契约确实不一致。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.api import notes as notes_api
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import Note, PlatformAccount, User


@pytest.fixture()
def ctx(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dedup.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    xhs = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="x", status="active"
    )
    dy = PlatformAccount(
        user_id=user.id, platform="douyin", sub_type="pc", nickname="d", status="active"
    )
    db.add_all([xhs, dy])
    db.commit()
    db.refresh(xhs)
    db.refresh(dy)

    # 已存在一条抖音笔记，note_id 与下面要保存的小红书 id 相同
    db.add(
        Note(
            user_id=user.id,
            platform="douyin",
            platform_account_id=dy.id,
            note_id="same-id",
            title="抖音原稿",
            content="抖音正文",
            source_type="douyin_extract",
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
        yield c, Session, user, xhs, dy
    db.close()


def test_same_note_id_on_another_platform_is_a_new_row(ctx):
    c, Session, user, xhs, dy = ctx

    response = c.post(
        "/api/notes/batch-save",
        json={
            "account_id": xhs.id,
            "notes": [
                {
                    "note_id": "same-id",
                    "title": "小红书新稿",
                    "content": "小红书正文",
                    "raw": {},
                }
            ],
        },
    )
    assert response.status_code == 200, response.text

    db = Session()
    rows = db.scalars(select(Note).where(Note.note_id == "same-id")).all()
    db.close()

    assert len(rows) == 2, "跨平台的同 id 必须各存一行，不能互相覆盖"
    by_platform = {r.platform: r for r in rows}
    assert by_platform["douyin"].title == "抖音原稿", "抖音那行被小红书 payload 覆盖了"
    assert by_platform["douyin"].content == "抖音正文"
    assert by_platform["xhs"].title == "小红书新稿"
    assert by_platform["xhs"].platform_account_id == xhs.id


def test_same_platform_same_id_still_updates_in_place(ctx):
    """加上 platform 之后，同平台的重复保存仍然要原地更新，不能变成两行。"""
    c, Session, user, xhs, dy = ctx

    for title in ("第一版", "第二版"):
        response = c.post(
            "/api/notes/batch-save",
            json={
                "account_id": xhs.id,
                "notes": [
                    {
                        "note_id": "xhs-only",
                        "title": title,
                        "content": "正文",
                        "raw": {},
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text

    db = Session()
    rows = db.scalars(select(Note).where(Note.note_id == "xhs-only")).all()
    db.close()

    assert len(rows) == 1, f"同平台重复保存产生了 {len(rows)} 行"
    assert rows[0].title == "第二版"
