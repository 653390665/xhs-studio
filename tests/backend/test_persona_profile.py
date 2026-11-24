"""账号画像已合并进创作 Skill：接口下线，账号身份只剩一个来源。

背景：画像表曾和 Skill 重复定义定位/人群/语气/禁区。两份说法不一致时
（例如画像说「结尾抛开放式问题，不做转化引导」，Skill 说「工具/清单一律加收藏」），
模型会取保守解，产出更公式化、更死板的稿子。现在统一由 Skill 提供身份。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models import PlatformAccount


def _client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'persona.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    register = client.post(
        "/api/auth/register", json={"username": "persona-profile", "password": "secret123"}
    )
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    session = TestingSession()
    account = PlatformAccount(
        user_id=register.json()["user"]["id"],
        platform="xhs",
        sub_type="pc",
        nickname="档案测试号",
        status="active",
    )
    session.add(account)
    session.commit()
    account_id = account.id
    session.close()
    return client, headers, account_id, lambda: app.dependency_overrides.pop(get_db, None)


def test_persona_endpoints_are_gone(tmp_path):
    """画像接口必须返回 410，并指向新的唯一来源。"""
    client, headers, account_id, cleanup = _client(tmp_path)
    try:
        read = client.get(f"/api/accounts/{account_id}/persona", headers=headers)
        assert read.status_code == 410
        assert "创作 Skill" in read.json()["detail"]

        write = client.put(
            f"/api/accounts/{account_id}/persona",
            headers=headers,
            json={"positioning": "测试定位"},
        )
        assert write.status_code == 410
    finally:
        cleanup()


def test_account_delete_no_longer_touches_persona(tmp_path):
    """删除账号仍然可用，只是不再清理已废弃的画像表。"""
    client, headers, account_id, cleanup = _client(tmp_path)
    try:
        removed = client.delete(f"/api/accounts/{account_id}", headers=headers)
        assert removed.status_code == 200
        assert removed.json()["status"] == "deleted"
    finally:
        cleanup()
