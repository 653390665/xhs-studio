"""列表响应瘦身：只剥 `raw_json`，正文保留全文。

## 为什么去掉截断

上一轮为了省体积把列表正文截到 400 字，活库实测 704 条里 **407 条被截**，
代价是五处功能说谎：

| 位置 | 症状 |
|---|---|
| `Library.tsx:279` | 「字数」列显示 400，而 id=589 实际 914 字 |
| `Library.tsx:727` | 展开行只能看半篇 |
| `NotePreview.tsx:111` | 原文抽屉同样只到 400 字 |
| `Studio.tsx:516` | 语料总字数少算 |
| `Library.tsx:129` | 关键字搜不到 400 字之后的内容 |

而归因是错的：撑大响应的是 `raw_json`，不是正文。

```
A 正文 400 字 + 无 raw_json    703K
B 全文      + 无 raw_json  1,344K   ← 现在走这条
C 全文      + raw_json     3,108K   ← 改造前
```

剥 raw_json 省 57%，截正文只再省 13%。不值得用五处错误换 13%。

## 为什么不干脆两样都做

正文是产品数据，raw_json 是抓取中间态。前者供人读，后者只有调试用
（`src/` 全部源码里 `raw_json` 出现 0 次）。
"""

from __future__ import annotations

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
        f"sqlite:///{tmp_path / 'lean.db'}", connect_args={"check_same_thread": False}
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

    db.add(
        Note(
            user_id=user.id,
            platform="xhs",
            platform_account_id=account.id,
            note_id="big",
            title="长正文",
            content="正" * 5000,
            source_type="discovery",
            raw_json={"blob": "x" * 20000, "source": "detail"},
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


def test_list_returns_full_body(client):
    """「字数」列、展开行、原文抽屉都读这个字段，截断会让它们全说谎。"""
    items = client.get("/api/notes?page_size=10").json()["items"]
    assert items, "列表为空"

    body = items[0]["content"]
    assert len(body) == 5000, (
        f"列表正文只有 {len(body)} 字——"
        "「字数」列会显示成这个数，展开行也只能看到这一段"
    )


def test_list_omits_raw_json(client):
    """前端源码里 `raw_json` 出现 0 次；列表下发它只是把 900 KB 白送出去。"""
    items = client.get("/api/notes?page_size=10").json()["items"]
    assert items[0]["raw_json"] is None


def test_detail_still_returns_full_body_and_raw_json(client):
    """详情页要完整正文和原始 payload，不能被列表的瘦身波及。"""
    detail = client.get("/api/notes/1").json()
    assert len(detail["content"]) == 5000
    assert detail["raw_json"]["source"] == "detail"
    assert detail["raw_json"]["blob"].startswith("x")


def test_payload_drops_raw_json_but_keeps_content(client):
    """整页响应里应该看不到那 20,000 字节的 blob，但正文一个字不少。"""
    payload = client.get("/api/notes?page_size=10").json()
    raw = client.get("/api/notes?page_size=10").content

    assert len(raw) < 60_000, f"单页响应 {len(raw)} B，raw_json 可能还在下发"
    assert len(payload["items"][0]["content"]) == 5000
