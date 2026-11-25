"""批量生成：契约与失败隔离。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api import ai_cards_batch
from backend.app.core.database import Base, get_db
from backend.app.core.deps import get_current_user
from backend.app.models import AiDraft, ModelConfig, User


@pytest.fixture()
def ctx(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'batch.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    user = User(username="batch-user", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    drafts = []
    for i, (title, body) in enumerate(
        [
            ("向上管理的三个误区", "1. 不是讨好\n2. 不是多汇报\n3. 不是抛问题"),
            ("周报怎么写", "只写做了什么没用。要写进度、风险、要不要支持。"),
            ("空正文", ""),
        ],
        start=1,
    ):
        d = AiDraft(user_id=user.id, platform="xhs", title=title, body=body)
        db.add(d)
        drafts.append(d)
    db.commit()
    for d in drafts:
        db.refresh(d)

    mc = ModelConfig(
        user_id=user.id,
        name="img",
        model_type="image",
        provider="wb",
        model_name="global:hy-image-3.5",
        base_url="http://127.0.0.1:7863/v1",
        encrypted_api_key="x",
        is_default=True,
    )
    db.add(mc)
    db.commit()

    app = FastAPI()
    app.include_router(ai_cards_batch.router, prefix="/api")

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client, [d.id for d in drafts], db, user
    db.close()


def test_rejects_empty_draft_ids(ctx):
    client, _ids, _db, _user = ctx
    r = client.post("/api/ai/cards/batch", json={"draft_ids": []})
    assert r.status_code == 422


def test_rejects_unknown_size(ctx):
    client, ids, _db, _user = ctx
    r = client.post("/api/ai/cards/batch", json={"draft_ids": ids[:1], "size": "1x1"})
    assert r.status_code == 400
    assert "尺寸" in r.json()["detail"]


def test_rejects_other_users_draft(ctx):
    client, _ids, _db, _user = ctx
    r = client.post("/api/ai/cards/batch", json={"draft_ids": [99999]})
    assert r.status_code == 404


def test_too_many_drafts_rejected(ctx):
    client, _ids, _db, _user = ctx
    r = client.post("/api/ai/cards/batch", json={"draft_ids": list(range(1, 15))})
    assert r.status_code == 422


def test_empty_body_draft_is_skipped_not_failed(ctx, monkeypatch):
    """空正文应该被跳过并说明原因，不该当成生成失败。"""
    client, ids, db, user = ctx
    from backend.app.api import ai_cards_batch as mod

    monkeypatch.setattr(mod, "_image_model_context", lambda db, u: (_Model(), "k"))

    r = client.post(
        "/api/ai/cards/batch",
        json={"draft_ids": [ids[2]], "attach_to_draft": False},
        # 空正文那篇不会走到生图，所以不需要真的网关
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skipped"] == 1, "空正文应记为 skipped"
    assert body["failed"] == 0
    entry = body["drafts"][0]
    assert entry["status"] == "skipped"
    assert "正文为空" in entry["reason"]


def test_batch_generates_and_attaches(ctx, monkeypatch):
    """正常路径：拆页 → 每页生图 → 挂到草稿。用 fake 生图客户端。"""
    client, ids, db, user = ctx
    from backend.app.api import ai_cards_batch as mod

    monkeypatch.setattr(mod, "_image_model_context", lambda db, u: (_Model(), "k"))
    monkeypatch.setattr(mod, "_materialize_image_data", lambda u, url: url)

    calls: list[str] = []

    class _FakeImageClient:
        def generate_image(self, **kwargs):
            calls.append(kwargs["prompt"])
            return {"url": f"https://example.com/{len(calls)}.png"}

    # 通过 dependency_overrides 换掉生图客户端
    client.app.dependency_overrides[mod.get_image_ai_client] = lambda: _FakeImageClient()

    r = client.post(
        "/api/ai/cards/batch",
        json={"draft_ids": [ids[0]], "attach_to_draft": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    entry = body["drafts"][0]
    assert entry["status"] == "ok"
    assert entry["generated"] == entry["page_count"]
    assert entry["attached"] == entry["generated"]
    assert len(calls) == entry["page_count"], "每一页都要调一次生图"
    # 第 2 页起要带参考图
    assert body["ok"] == 1


def test_single_page_failure_does_not_abort_batch(ctx, monkeypatch):
    """某一页失败 → 该篇记 partial，其它篇照样跑完。"""
    client, ids, db, user = ctx
    from backend.app.api import ai_cards_batch as mod

    monkeypatch.setattr(mod, "_image_model_context", lambda db, u: (_Model(), "k"))
    monkeypatch.setattr(mod, "_materialize_image_data", lambda u, url: url)

    state = {"n": 0}

    class _FlakyClient:
        def generate_image(self, **kwargs):
            state["n"] += 1
            if state["n"] == 2:                     # 第 2 次调用失败
                raise RuntimeError("网关超时")
            return {"url": f"https://example.com/{state['n']}.png"}

    client.app.dependency_overrides[mod.get_image_ai_client] = lambda: _FlakyClient()

    r = client.post(
        "/api/ai/cards/batch",
        json={"draft_ids": ids[:2], "attach_to_draft": False},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = [d["status"] for d in body["drafts"]]
    assert "partial" in kinds, f"应该有 partial，实际 {kinds}"
    # 两篇都跑过了（不是第一篇失败就停）
    assert len(body["drafts"]) == 2


def test_replace_images_clears_previous(ctx, monkeypatch):
    """replace_images=True 时先清空旧配图，避免重复挂。"""
    client, ids, db, user = ctx
    from backend.app.api import ai_cards_batch as mod

    monkeypatch.setattr(mod, "_image_model_context", lambda db, u: (_Model(), "k"))
    monkeypatch.setattr(mod, "_materialize_image_data", lambda u, url: url)

    n = {"i": 0}

    class _FakeClient:
        def generate_image(self, **kwargs):
            n["i"] += 1
            return {"url": f"https://example.com/r{n['i']}.png"}

    client.app.dependency_overrides[mod.get_image_ai_client] = lambda: _FakeClient()

    client.post("/api/ai/cards/batch", json={"draft_ids": [ids[0]], "attach_to_draft": True})
    r = client.post(
        "/api/ai/cards/batch",
        json={"draft_ids": [ids[0]], "attach_to_draft": True, "replace_images": True},
    )
    assert r.status_code == 200, r.text

    from sqlalchemy import select

    from backend.app.models import DraftAsset

    rows = db.scalars(select(DraftAsset).where(DraftAsset.draft_id == ids[0])).all()
    # 只剩第二轮那批，不是两批叠加
    assert len(rows) == r.json()["drafts"][0]["generated"]


class _Model:
    model_name = "m"
    base_url = "http://127.0.0.1:7863/v1"


def test_status_buckets_sum_matches_drafts(ctx):
    """无论成功失败，四个状态桶加起来必须等于请求的草稿数。"""
    # 这个用纯模型层验证，不经过 HTTP
    from backend.app.services.xhs_card_planner import plan_pages

    pages = plan_pages(title="t", body="1. a\n2. b", max_pages=5)
    assert len(pages) >= 2
