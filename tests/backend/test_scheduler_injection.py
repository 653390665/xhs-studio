"""定时任务的写法注入：必须和手动路径看到同一份内容。

这是第一步止血里改的四处之一，但 868 条测试里没有一条专门盯它。
调度器原来做的是 ``content_md[:4000]`` 裸切：证据型会被喂整份报告，
长手册会在句子中间被裁断。这两件事在无人值守时最难被发现——没人看着输出。
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import PlatformAccount, StyleProfile, User
from backend.app.services.scheduler_service import _auto_task_instruction

RULES = ["- 每篇开头先给具体场景", "- 每段不超过三行"]

REPORT_MD = """# 风格 Skill：ego 风格

## 1. 硬规则（写稿必须遵守）

- **要求**：每篇至少出现一次明确反转。

## 3. 自述与实测不一致（不写进生成要求）

- 这条不该进提示词。
"""

LONG_MD = (
    "## 数据日志\n" + ("日志。" * 1200) + "\n"
    "## 定位\n写给做 AI 产品的人。\n"
    "## 禁区\n不要写收益承诺。\n"
    "## 变现\n" + ("变现。" * 400) + "\n"
)


class _Task:
    ai_instruction = ""  # 用默认那句


def _session(tmp_path, name):
    engine = create_engine(
        f"sqlite:///{tmp_path / (name + '.db')}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _setup(tmp_path, profile_md, *, engine="heuristic", source="library", meta=None):
    db = _session(tmp_path, f"sched-{engine}-{source}")
    user = User(username=f"sched-{engine}-{source}", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="测试号", status="active"
    )
    db.add(account)
    db.flush()
    db.add(
        StyleProfile(
            user_id=user.id,
            account_id=account.id,
            name="测试写法",
            status="applied",
            source=source,
            works_count=147,
            char_count=len(profile_md),
            engine=engine,
            profile_json=meta or {},
            skill_md=profile_md,
        )
    )
    db.commit()
    db.refresh(account)
    return db, user, account


def _instruction(db, user, account):
    return _auto_task_instruction(
        db, user, _Task(), account, {"title": "测试选题"}, "测试关键词"
    )


def test_scheduler_injects_evidence_rules_not_the_report(tmp_path):
    db, user, account = _setup(
        tmp_path,
        REPORT_MD,
        engine="evidence",
        source="evidence_distill",
        meta={"method": "hypothesis-then-evidence", "injectable_rules": RULES},
    )
    try:
        text = _instruction(db, user, account)

        assert "每篇开头先给具体场景" in text, "证据型的规则必须真的进提示词"
        assert "自述与实测不一致" not in text, "报告段落不能当指令"
        assert "## 1. 硬规则" not in text
    finally:
        db.close()


def test_scheduler_keeps_decisions_when_handbook_exceeds_budget(tmp_path):
    db, user, account = _setup(tmp_path, LONG_MD)
    try:
        text = _instruction(db, user, account)

        assert "定位" in text and "禁区" in text, "预算不够时先保决定性小节"
        assert "数据日志" not in text, "记账类小节应先丢"
        assert "因长度省略" in text, "被裁掉时要如实说明"
    finally:
        db.close()


def test_scheduler_omits_style_when_account_has_none(tmp_path):
    db = _session(tmp_path, "sched-empty")
    user = User(username="sched-empty", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="空号", status="active"
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    try:
        text = _instruction(db, user, account)

        assert "写作风格" not in text, "没有 applied 写法时不该凭空造一段"
        assert "改写为原创小红书笔记" in text
    finally:
        db.close()


def test_scheduler_and_manual_path_see_the_same_block(tmp_path):
    """同一个 profile，定时任务与手动生成拿到的写法正文必须逐字一致。"""
    from backend.app.services.account_context_service import (
        active_creation_skill,
        style_prompt_block,
    )

    db, user, account = _setup(
        tmp_path,
        REPORT_MD,
        engine="evidence",
        source="evidence_distill",
        meta={"method": "hypothesis-then-evidence", "injectable_rules": RULES},
    )
    try:
        view = active_creation_skill(db, user, account.id)
        manual = style_prompt_block(view, max_chars=8000).strip()
        scheduled = style_prompt_block(view, max_chars=4000).strip()

        assert manual == scheduled, "同一个 profile 不该因为调用方不同而内容不同"
        assert manual.startswith("【写作风格：")
    finally:
        db.close()
