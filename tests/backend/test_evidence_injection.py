"""证据蒸馏产物必须真的进入生成，且只注入规则。

The distiller produces two artifacts: ``injectable_rules`` (what a model should
follow) and ``skill_md`` (a report for humans with coverage bars and headings).
Before this was pinned, applying an evidence profile fed the *report* into the
prompt — 3,124 characters of Markdown where 204 characters of rules would do,
and the model was asked to follow headings instead of instructions.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import PlatformAccount, StyleProfile, User
from backend.app.services.account_context_service import (
    _evidence_rule_block,
    account_skill_block,
    active_creation_skill,
)

RULES = [
    "每篇至少出现一次明确反转：先承认大众说法，再给出自己的判断。（93% 篇目成立）",
    "每个关键判断配一个具体细节，不接受只有结论的段落。（94% 篇目成立）",
    "单句控制在一个呼吸内，长句拆开。（88% 篇目成立）",
]

# A report-shaped Markdown body: headings, coverage bars, sections a model cannot
# act on. This is what must NOT reach the prompt.
REPORT_MD = """# 风格 Skill：ego 风格（验证集）

## 0. 这份产物的证据基础

- 语料：ego 154 篇抖音口播，147 篇可用
- 判定：硬规则 4 条 / 倾向 1 条 / 设计选择 6 条

## 1. 硬规则（写稿必须遵守）

### 反认知/转折句式

- **要求**：每篇至少出现一次明确反转。
- **覆盖率**：93%（137/147 篇） `██████████████████··`
"""


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'evidence-inject.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _setup(tmp_path, *, method: str = "hypothesis-then-evidence", status: str = "applied"):
    db = _session(tmp_path)
    user = User(username=f"inject-{method}-{status}", password_hash="x")
    db.add(user)
    db.flush()
    account = PlatformAccount(
        user_id=user.id, platform="xhs", sub_type="pc", nickname="测试号", status="active"
    )
    db.add(account)
    db.flush()
    profile = StyleProfile(
        user_id=user.id,
        account_id=account.id,
        name="ego 风格（验证集）",
        status=status,
        source="evidence_distill",
        works_count=147,
        char_count=len(REPORT_MD),
        engine="evidence",
        profile_json={
            "method": method,
            "injectable_rules": RULES,
            "report": {"summary": {}},
        },
        skill_md=REPORT_MD,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    db.refresh(account)
    return db, user, account, profile


def test_evidence_profile_injects_rules_not_the_report(tmp_path):
    db, user, account, _ = _setup(tmp_path)
    try:
        block = account_skill_block(db, user, account)

        assert "每篇至少出现一次明确反转" in block, "规则必须注入"
        assert "单句控制在一个呼吸内" in block
        assert "## 0. 这份产物的证据基础" not in block, "报告不应注入"
        assert "覆盖率" not in block or "篇目成立" in block
        assert len(block) < 1200, f"注入块应紧凑，实际 {len(block)} 字符"
        # No double bullet: the stored rules already carry "- ", and the block
        # used to prepend another one ("- - 每篇…").
        assert "- - " not in block, "规则前出现双横线"
    finally:
        db.close()


def test_rule_block_absent_for_legacy_profiles(tmp_path):
    """Old statistical profiles have no structural rules; they keep the old path."""
    db, user, account, _ = _setup(tmp_path, method="llm")
    try:
        view = active_creation_skill(db, user, account.id)
        assert view is not None
        assert _evidence_rule_block(view) == ""

        block = account_skill_block(db, user, account)
        assert "风格 Skill：ego 风格" in block, "旧风格仍按全文注入"
    finally:
        db.close()


def test_ready_profile_is_not_injected(tmp_path):
    """A ready profile is a candidate, not the active identity."""
    db, user, account, _ = _setup(tmp_path, status="ready")
    try:
        view = active_creation_skill(db, user, account.id)
        assert view is None, "未应用的风格不能生效"

        block = account_skill_block(db, user, account)
        assert "每篇至少出现一次明确反转" not in block
    finally:
        db.close()


def test_applying_an_evidence_profile_activates_the_rules(tmp_path):
    """ready -> applied is the only switch that makes rules reach generation."""
    from backend.app.services.style_distill_service import apply_to_account

    db, user, account, profile = _setup(tmp_path, status="ready")
    try:
        assert "每篇至少出现一次明确反转" not in account_skill_block(db, user, account)

        apply_to_account(db, user, profile, account_id=account.id)

        block = account_skill_block(db, user, account)
        assert "每篇至少出现一次明确反转" in block
    finally:
        db.close()
