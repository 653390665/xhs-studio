"""apply_draft 的调用契约：关键字参数。

这一条是被「跑一遍真实请求」抓出来的：`apply_draft` 的签名是

    def apply_draft(db, user, *, account_id, draft, source=...)

`account_id` 与 `draft` 是**keyword-only**，但两处调用点都按位置传：

    apply_draft(db, current_user, resolved, payload.draft, source=...)

TypeError，接口 500。静态扫描和单测都没抓到，因为：
  · 单元测试直接 `pgs.apply_draft(db, user, account_id=..., ...)`（对的）
  · 接口测试没覆盖 apply-draft 的 happy path
  · 没有类型检查跑在这个项目上

所以这里钉两件事：
1. 签名保持 keyword-only（防止有人改成位置参数又让调用点悄悄能用）；
2. 所有调用点都用关键字传参。
"""

from __future__ import annotations
import re
from pathlib import Path

import pytest

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend" / "app"

def _read(rel: str) -> str:
    return (BACKEND / rel).read_text(encoding="utf-8", errors="replace")


def test_apply_draft_keeps_keyword_only_signature():
    service = _read("services/positioning_guide_service.py")
    start = service.find("def apply_draft(")
    assert start > 0
    header = service[start : service.find(") ->", start)]
    assert "*," in header, "account_id/draft 必须保持 keyword-only"
    assert "account_id: int" in header
    assert "draft: dict" in header


def test_all_callers_pass_keywords():
    """位置传参会 TypeError —— 这是 500 的直接原因。"""
    offenders = []
    for path in BACKEND.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if "apply_draft(" in line and "def apply_draft" not in line:
                # 收集这次调用的参数文本（跨行，最多看 6 行）
                chunk = "\n".join(text.splitlines()[i - 1 : i + 5])
                head = chunk[chunk.find("apply_draft(") :]
                # 取到配对的右括号
                depth = 0
                args = ""
                for ch in head[head.find("(") :]:
                    if ch == "(":
                        depth += 1
                        continue
                    if ch == ")":
                        depth -= 1
                        if depth == 0:
                            break
                        continue
                    args += ch
                if "account_id=" not in args or "draft=" not in args:
                    offenders.append(f"{path.relative_to(BACKEND)}:{i}")
    assert not offenders, (
        "这些调用点没用关键字传参（会 TypeError → 500）：" + "、".join(offenders)
    )


def test_apply_draft_endpoint_reaches_the_service(tmp_path):
    """接口 happy path 必须真的走通，而不只是「路由存在」。

    之前只有一条「路由注册了」的断言，所以 500 一直没被发现。
    """
    import sys

    sys.path.insert(0, str(REPO))

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.api import account_positioning as api
    from backend.app.core.database import Base, get_db
    from backend.app.core.deps import get_current_user
    from backend.app.models import PlatformAccount, User

    # 用文件而不是 :memory:：每个请求会拿新 session，内存库不共享连接。
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pos.db'}", connect_args={"check_same_thread": False}
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
    account_id = account.id

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

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post(
            "/api/xhs/account-positioning/apply-draft",
            json={
                "account_id": account_id,
                "draft": {"positioning": "帮中层做向上沟通"},
                "source": "verify",
            },
        )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["positioning"] == "帮中层做向上沟通"
    db.close()
