"""路由预演必须和实际注入一致。

行为约定（`module_skill_text` 里写着的）：路由 0 命中且点名了模块时，
生成阶段会退回本模块自己的 Skill `rows[:limit]` —— 静默丢掉整个模块比
注入一条略不相关的更糟。

问题在于预演原来只返回 `items=[]` + `near_misses`，界面就说「没有命中任何
Skill」。而实际 prompt 里有 3922 字的方法论。用户对着一句「没命中」去排查，
永远查不出稿子里的那段规则是从哪来的。

所以 `/route` 现在额外返回 `fallback_items`，界面照实显示。
"""

from __future__ import annotations

import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api import skill_library as api
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import SkillLibraryItem, User


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'skill.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    # draft 模块一条，内容与「AI 工具怎么选」不匹配（确保路由打不中）
    db.add(
        SkillLibraryItem(
            user_id=user.id,
            slug="wb-xhs-humanize-compliance",
            name="去 AI 味与发布检查",
            module="draft",
            description="去 AI 味",
            triggers="",
            content_md="# 去 AI 味\n" + "规则。" * 400,
            source="test",
            license="",
            enabled=True,
            sort_order=10,
        )
    )
    db.commit()

    app = FastAPI()
    app.include_router(api.router, prefix="/api")

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as c:
        yield c
    db.close()


def test_zero_hits_still_reports_what_will_be_injected(client):
    """预演说 0 命中，但也必须说清「实际会注入哪条」。"""
    resp = client.post(
        "/api/xhs/skill-library/route",
        json={"task": "AI 工具怎么选，写一篇小红书笔记", "module": "draft", "limit": 3},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["items"] == [], "这条任务不该命中 draft 模块的 Skill"
    assert payload["near_misses"] is not None

    fb = payload.get("fallback_items") or []
    assert len(fb) == 1, f"没返回兜底项，界面会说「什么都没注入」：{payload}"
    assert fb[0]["slug"] == "wb-xhs-humanize-compliance"
    assert fb[0]["content_chars"] > 100
    assert payload.get("fallback_reason")


def test_no_module_means_no_fallback(client):
    """不限定模块时，前端生成阶段不会兜底 —— 预演也不该说有。"""
    resp = client.post(
        "/api/xhs/skill-library/route",
        json={"task": "完全不相关的一句话 xyzzy", "limit": 3},
    )
    payload = resp.json()
    assert payload["items"] == []
    assert payload.get("fallback_items") == []


def test_fallback_matches_what_module_skill_text_actually_returns(client):
    """这条是核心：预演的兜底项必须等于生成时真正注入的那条。

    两边算的是同一件事，一旦分叉，界面又开始骗人。
    """
    import backend.app.core.database as dbmod

    resp = client.post(
        "/api/xhs/skill-library/route",
        json={"task": "AI 工具怎么选，写一篇小红书笔记", "module": "draft", "limit": 3},
    )
    payload = resp.json()
    fallback = payload.get("fallback_items") or []
    assert fallback

    # 直接调生成侧（同一个库、同一个用户）
    session = next(client.app.dependency_overrides[dbmod.get_db]())
    try:
        from backend.app.services.skill_library_service import module_skill_text

        user = session.query(User).first()
        text = module_skill_text(
            session, user, "draft", query="AI 工具怎么选，写一篇小红书笔记", limit=3
        )
    finally:
        session.close()

    assert text, "生成侧什么都没注入，但预演说有兜底 —— 两边不一致"
    assert fallback[0]["name"] in text, (
        f"预演说会注入「{fallback[0]['name']}」，实际注入的是别的：{text[:120]}"
    )
