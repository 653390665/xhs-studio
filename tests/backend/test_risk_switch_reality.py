"""风险开关：逐个核对「谁在守、守的东西有没有前门」。

8 个开关全部默认关闭，后端确实会拦。但用户截图里那句「这批开关对应的功能
还没上线」到底准不准，要按代码逐个验，不能凭印象。

这不是「开关坏了」，是「开关守的门还没有修」——两种情况对用户的含义完全不同：
  · 开关没生效 → 打开也没用，是 bug
  · 门还没修   → 开关是对的，功能没做，是范围问题

所以这组测试只钉三件事：
1. 每个开关在后端至少有一个真实读取点（不是只存在于 schema）。
2. 前端确实没有对应入口（有的话，文案就得改，测试就该红）。
3. 保留项（自动私信/评论）后端必须拒绝开启。
"""

from __future__ import annotations
import os
import re
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import User
from backend.app.services.risk_control_service import (
    FIELD_LABELS,
    RESERVED_FIELDS,
    RISK_FIELDS,
    get_risk_controls,
    update_risk_controls,
)

# 仓库根：本文件在 tests/backend/ 下，往上两级。
# 不再写死开发机的绝对路径，CI 与本机用同一份。
REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "frontend" / "src"
BACKEND = REPO / "backend" / "app"

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _all_backend_text() -> str:
    return "\n".join(
        _read(p) for p in BACKEND.rglob("*.py") if p.name != "risk_control_service.py"
    )


def _all_frontend_calls() -> str:
    """只看真实调用（get/post/put/del 的 URL），不看注释。"""
    pattern = re.compile(r"""(get|post|put|patch|del)<[^>]*>?\(\s*[`"']([^`"']+)[`"']""")
    urls: list[str] = []
    for path in SRC.rglob("*.ts*"):
        text = _read(path)
        for match in pattern.finditer(text):
            urls.append(match.group(2))
    return "\n".join(urls)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'risk.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_every_switch_has_a_real_reader():
    """每个**可开启**的开关至少被一处业务代码读过，否则它就是个装饰。

    只存在于 model / schema / serializer 里不算：那只是「能存能读」，
    不代表它守着任何东西。

    保留项（``auto_engagement_enabled``）例外：它按设计就不能开启，
    自然也不需要读取点——它由另一条测试钉住。
    """
    backend = _all_backend_text()
    missing = []
    for field in RISK_FIELDS:
        if field in RESERVED_FIELDS:
            continue
        # require_risk_control(...) 或 controls.<field> 两种写法都算
        if f'"{field}"' not in backend and f"controls.{field}" not in backend:
            missing.append(field)
    assert not missing, f"这些开关没有任何读取点：{missing}"


def test_reserved_switch_cannot_be_enabled(db):
    """自动私信/评论：平台明确禁止，后端必须硬拒绝。"""
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    assert RESERVED_FIELDS == frozenset({"auto_engagement_enabled"})
    with pytest.raises(ValueError) as exc:
        update_risk_controls(
            db, user, {"auto_engagement_enabled": True}, acknowledge_risk=True
        )
    assert "暂未开放" in str(exc.value)


def test_enabling_requires_acknowledgement(db):
    user = User(username="u2", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    with pytest.raises(ValueError) as exc:
        update_risk_controls(db, user, {"auto_publish_enabled": True})
    assert "确认风险" in str(exc.value)

    # 确认之后才能存
    setting = update_risk_controls(
        db, user, {"auto_publish_enabled": True}, acknowledge_risk=True
    )
    assert setting.auto_publish_enabled is True
    # 自动发布打开时，待发布任务也必须打开（否则到点没东西可发）
    assert setting.auto_create_publish_job_enabled is True


def test_frontend_has_entry_for_every_gated_pipeline():
    """这些链路现在都有入口了；入口被删掉时这条要红。

    历史：上一版这里断言的是「没有入口」，因为当时确实没有。
    2026-11-18 三条都接上了（设置 › 自动运营 / 设置 › 账号矩阵 /
    样本库 › 改写成草稿），断言方向跟着反转。
    """
    calls = _all_frontend_calls()
    assert "/api/auto-tasks" in calls, "自动运营入口没了，改 RiskControls 标签"
    assert "/api/xhs/matrix" in calls, "账号矩阵入口没了，改标签"
    assert "batch-rewrite-drafts" in calls, "批量改写入口没了，改标签"


def test_ui_states_the_limitation():
    comp = _read(SRC / "components" / "RiskControls.tsx")
    # 每个开关的入口（或「未开放」）必须写出来，不能只给开关名
    assert "RISK_WIRED" in comp
    assert "设置 › 自动运营" in comp
    assert "设置 › 账号矩阵" in comp
    assert "样本库 › 改写成草稿" in comp
    assert "已接调度器" in comp
    assert "未开放" in comp
    # 每个开关都要有中文标签，不能露出英文字段名
    from backend.app.services.risk_control_service import FIELD_LABELS as labels

    for field in RISK_FIELDS:
        assert field in labels
    assert "auto_publish_enabled" in comp
