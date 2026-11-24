"""账号身份的注入必须优先保留红线，而不是按长度硬切。

Regression: ``account_skill_block`` used ``content[:max_chars]``. A long profile
lost its 禁区 (red lines) section off the end, so generation got "how to make
money" but not "what you must never write".
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import PlatformAccount, StyleProfile, User
from backend.app.services.account_context_service import account_skill_block


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'identity-block.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _setup(tmp_path, skill_md: str):
    db = _session(tmp_path)
    user = User(username=f"identity-{abs(hash(skill_md)) % 10000}", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        nickname="测试号",
        status="active",
    )
    db.add(account)
    db.flush()
    db.add(
        StyleProfile(
            user_id=user.id,
            account_id=account.id,
            name="身份",
            status="applied",
            source="skill_workflow",
            works_count=1,
            char_count=len(skill_md),
            engine="skill_workflow",
            profile_json={},
            skill_md=skill_md,
        )
    )
    db.commit()
    return db, user, account


def test_without_active_style_says_so(tmp_path):
    db = _session(tmp_path)
    try:
        user = User(username="no-style", password_hash="x")
        db.add(user)
        db.flush()
        account = PlatformAccount(
            user_id=user.id, platform="xhs", sub_type="pc", nickname="空号", status="active"
        )
        db.add(account)
        db.commit()

        block = account_skill_block(db, user, account)

        assert "还没有生效的写作风格" in block
    finally:
        db.close()


def test_short_profile_is_passed_through_whole(tmp_path):
    db, user, account = _setup(tmp_path, "## 1. 一句话定位\n\n做宁波一人公司记录。")
    try:
        block = account_skill_block(db, user, account)

        assert "做宁波一人公司记录" in block
        assert "因长度省略" not in block
    finally:
        db.close()


def test_over_budget_keeps_red_lines(tmp_path):
    """A 禁区 section at the end of a long profile must not be trimmed away."""
    filler = "\n\n".join(
        f"## {index}. 数据日志 {index}\n\n" + ("这是很长的日志内容。" * 60)
        for index in range(1, 9)
    )
    md = (
        "## 1. 一句话定位\n\n宁波一人公司记录者。\n\n"
        + filler
        + "\n\n## 9. 禁区（红线）\n\n不承诺收益；不编造案例；不做工具清单号。"
    )
    db, user, account = _setup(tmp_path, md)
    try:
        block = account_skill_block(db, user, account, max_chars=3000)

        assert len(block) < 3400, "budget must still be respected"
        assert "不承诺收益" in block, "red lines must survive the cut"
        assert "宁波一人公司记录者" in block, "positioning must survive the cut"
        assert "因长度省略" in block, "the reader must know sections were dropped"
    finally:
        db.close()


def test_over_budget_drops_bookkeeping_first(tmp_path):
    """数据日志 / 未确认清单 are the first things to go, not the定位."""
    md = (
        "## 1. 一句话定位\n\n核心定位内容。\n\n"
        "## 2. 禁区（红线）\n\n不承诺收益。\n\n"
        "## 3. 数据日志\n\n" + ("日志" * 400) + "\n\n"
        "## 4. 未确认清单\n\n" + ("待定事项" * 200)
    )
    db, user, account = _setup(tmp_path, md)
    try:
        block = account_skill_block(db, user, account, max_chars=400)

        assert "核心定位内容" in block
        assert "不承诺收益" in block
        assert "日志日志" not in block, "bookkeeping must be dropped before red lines"
    finally:
        db.close()
