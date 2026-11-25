"""接口层验证：/api/ai/cards/plan 与 /api/ai/cards/presets。

生成接口要真调网关，那部分放到本地实跑里验；这里只守契约。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api import ai_cards
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AiDraft, User


@pytest.fixture()
def ctx(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cards.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="card-user", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    draft = AiDraft(user_id=user.id, platform="xhs", title="向上管理的三个误区",
                    body="1. 不是讨好，是降低信息差\n2. 不是多汇报，是随时答得上\n3. 不是抛问题，是给选项")
    db.add(draft)
    db.commit()
    db.refresh(draft)

    app = FastAPI()
    app.include_router(ai_cards.router, prefix="/api")

    def _db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client, draft.id
    db.close()


def test_presets_endpoint(ctx):
    client, _ = ctx
    r = client.get("/api/ai/cards/presets")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_size"] == "1024x1365"
    assert body["styles"] and body["layouts"] and body["presets"]


def test_plan_from_raw_text(ctx):
    client, _ = ctx
    r = client.post("/api/ai/cards/plan", json={
        "title": "为什么你的周报没人看",
        "body": "大部分周报只写了做了什么。上级只想确认进度、风险、要不要他出手。",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert body["pages"][0]["type"] == "cover"
    assert body["pages"][0]["title"] == "为什么你的周报没人看"


def test_plan_from_draft_id(ctx):
    client, draft_id = ctx
    r = client.post("/api/ai/cards/plan", json={"body": "占位", "draft_id": draft_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pages"][0]["title"] == "向上管理的三个误区", "应从草稿取标题"


def test_plan_rejects_other_users_draft(ctx):
    client, _ = ctx
    r = client.post("/api/ai/cards/plan", json={"body": "x", "draft_id": 99999})
    assert r.status_code == 404


def test_generate_rejects_unknown_size(ctx):
    client, _ = ctx
    r = client.post("/api/ai/cards/generate", json={
        "pages": [{"type": "cover", "title": "标题", "lines": []}],
        "size": "800x800",
    })
    assert r.status_code == 400
    assert "尺寸" in r.json()["detail"]


def test_generate_requires_pages(ctx):
    client, _ = ctx
    r = client.post("/api/ai/cards/generate", json={"pages": []})
    assert r.status_code == 422
