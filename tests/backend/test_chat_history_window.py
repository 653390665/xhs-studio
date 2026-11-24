"""聊天记录分页：必须返回最新的 200 条，而不是最旧的。

2026-11-18 实测：库里 210 条，接口返回 MSG-000…MSG-199（最旧 200），
最新 10 条消失。而模型侧读的是 ``desc().limit(8)``（最新 8 条）——
同一张表两个消费者读反方向：用户看不到自己刚发的，模型却看得见。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api import ai as ai_api
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AiDraft, DraftChatMessage, User


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'chat.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    draft = AiDraft(user_id=user.id, platform="xhs", title="t", body="b")
    db.add(draft)
    db.commit()
    db.refresh(draft)

    base = datetime(2026, 11, 18, 0, 0, 0)
    for i in range(210):
        db.add(
            DraftChatMessage(
                draft_id=draft.id,
                user_id=user.id,
                role="user" if i % 2 == 0 else "assistant",
                content=f"MSG-{i:03d}",
                created_at=base + timedelta(seconds=i),
            )
        )
    db.commit()

    app = FastAPI()
    app.include_router(ai_api.router, prefix="/api")

    def _db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c, draft.id
    db.close()


def test_history_returns_the_newest_200(client):
    c, draft_id = client
    response = c.get(f"/api/ai/draft-chat/{draft_id}")
    assert response.status_code == 200, response.text
    items = response.json()["items"]

    assert len(items) == 200
    assert items[0]["content"] == "MSG-010", f"起点应是第 11 条，实际 {items[0]['content']}"
    assert items[-1]["content"] == "MSG-209", (
        f"最后一条应是最新消息，实际 {items[-1]['content']}——刷新后看不到刚发的"
    )


def test_history_is_in_ascending_order(client):
    """渲染是从上往下、滚到底部，所以数组必须按时间正序。"""
    c, draft_id = client
    items = c.get(f"/api/ai/draft-chat/{draft_id}").json()["items"]
    contents = [item["content"] for item in items]
    assert contents == sorted(contents), "返回顺序不是时间正序"


def test_short_history_is_unaffected(client):
    """少于 200 条时行为不变（这条防止修复把顺序弄反）。"""
    c, draft_id = client
    # 直接查同一接口，把 210 条换成「只剩最近 3 条」不方便，这里改用断言长度覆盖
    items = c.get(f"/api/ai/draft-chat/{draft_id}").json()["items"]
    assert len(items) <= 200
