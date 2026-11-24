"""定位起草：把「六个空框」变成「一份能改的草稿」。

这组测试只测**边界**，不测模型输出质量（那取决于 prompt，不是断言能钉的）：

  · 没有账号 → 400，不静默返回空草稿
  · 库里没有带正文的样本 → 400，别让用户对着空草稿猜
  · 有样本时返回 6 个字段（可能为空字符串，但键必须在）
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import Note, PlatformAccount, User


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'pos.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="pos-user", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    from backend.app.api import account_positioning

    app = FastAPI()
    app.include_router(account_positioning.router, prefix="/api")

    def _db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user

    with TestClient(app) as c:
        yield c, Session, user, app
    db.close()


def test_draft_without_account_is_rejected(client):
    c, _, _, _ = client
    response = c.post("/api/xhs/account-positioning/draft", json={})
    assert response.status_code == 400
    assert "账号" in response.json()["detail"]


def test_draft_without_notes_is_rejected(client):
    """库里没样本时不能假装能起草——空草稿比报错更让人困惑。"""
    c, Session, user, _app = client
    db = Session()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", status="active"
    )
    db.add(account)
    db.commit()
    account_id = account.id
    db.close()

    response = c.post(
        "/api/xhs/account-positioning/draft", json={"account_id": account_id}
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "笔记" in detail or "样本" in detail
    # 没有自己的笔记时，必须把用户引到引导式定稿，而不是让他反复重试
    assert "引导式定稿" in detail


def test_draft_returns_all_six_fields(client, monkeypatch):
    """六个键必须都在，哪怕值是空的——前端按 key 填表，缺键会渲染成 undefined。"""
    c, Session, user, app = client
    db = Session()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", status="active"
    )
    db.add(account)
    db.flush()
    db.add(
        Note(
            user_id=user.id,
            platform_account_id=account.id,
            platform="xhs",
            note_id="n-1",
            title="测试笔记",
            content="这是一段足够长的正文，用来触发定位起草。" * 5,
            # 必须是账号自己发的：起草只认 creator / publish，
            # 用 discovery 会拿到样本作者的赛道（这正是之前的 bug）。
            source_type="creator",
        )
    )
    db.commit()
    account_id = account.id
    db.close()

    class FakeClient:
        def complete(self, **kwargs):
            return (
                '{"positioning":"我帮谁解决什么","audience":"一人公司",'
                '"promise":"稳定拿到方法","main_topics":["AI 工具"],'
                '"taboos":["不做收益承诺"],"language_samples":["先说结论"]}'
            )

    from backend.app.api import account_positioning

    # Depends() 在注册路由时就抓住了函数对象，改模块属性没用，
    # 必须走 dependency_overrides。
    app.dependency_overrides[account_positioning.get_text_ai_client] = (
        lambda: FakeClient()
    )
    monkeypatch.setattr(
        account_positioning, "_text_model_context", lambda db, user: (object(), "k")
    )

    response = c.post(
        "/api/xhs/account-positioning/draft", json={"account_id": account_id}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_notes"] >= 1
    assert set(body["draft"]) == {
        "positioning",
        "audience",
        "promise",
        "main_topics",
        "taboos",
        "language_samples",
    }
    # 起草不落库：GET 回来仍然是空的
    assert c.get(f"/api/xhs/account-positioning?account_id={account_id}").json()[
        "is_empty"
    ] is True
