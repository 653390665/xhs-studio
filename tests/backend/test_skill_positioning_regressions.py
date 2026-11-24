"""定位：引导确认不能删数据，is_empty 不能和注入字段不一致。

两条都是 2026-11-18 实测出来的：

* ``apply_draft`` 对 list 字段无条件写入，空数组会清掉用户以前填的禁区；
  而文本字段的空串一直是被跳过的 —— 同一个「未答」两种效果。
* ``is_empty`` 检查 ``promise``，但 ``PROMPT_FIELDS`` 不含它，于是只填
  「内容承诺」时被判定为「定位已就绪」，注入的却是一段全是 ``[]`` 的空壳，
  ``ai.py`` 还会在它后面追加「以上是账号的真实情况」。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import AccountPositioning, PlatformAccount, User
from backend.app.services import positioning_guide_service as pgs
from backend.app.services.account_positioning_service import (
    PROMPT_FIELDS,
    is_empty,
    positioning_block,
)


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pos.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _account(db):
    user = User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    account = PlatformAccount(
        user_id=user.id,
        platform="xhs",
        sub_type="pc",
        nickname="a",
        status="active",
        profile_json=json.dumps({}),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return user, account


def test_apply_draft_does_not_clear_unanswered_list_fields(db):
    """引导里跳过「禁区」这一问，不能把以前填的禁区删掉。"""
    user, account = _account(db)
    record = AccountPositioning(
        user_id=user.id,
        platform_account_id=account.id,
        positioning="原有定位",
        taboos=["不露脸"],
        language_samples=["先说结论"],
        main_topics=["品牌战略"],
        source="manual",
    )
    db.add(record)
    db.commit()

    pgs.apply_draft(
        db,
        user,
        account_id=account.id,
        draft={
            "positioning": "",
            "audience": "刚成立一人公司的创业者",
            "promise": "",
            "main_topics": [],
            "taboos": [],
            "language_samples": [],
        },
    )
    db.refresh(record)

    assert record.positioning == "原有定位", "文本字段的空值应该被跳过"
    assert record.taboos == ["不露脸"], "未回答禁区不该删掉已保存的禁区"
    assert record.language_samples == ["先说结论"]
    assert record.main_topics == ["品牌战略"]
    # 答了的那一项要写进去
    assert record.audience == "刚成立一人公司的创业者"


def test_apply_draft_can_still_write_non_empty_lists(db):
    """「空 = 不动」不能反过来变成「永远写不进去」。"""
    user, account = _account(db)
    record = AccountPositioning(
        user_id=user.id,
        platform_account_id=account.id,
        positioning="",
        audience="",
        promise="",
        taboos=["旧的"],
        language_samples=[],
        main_topics=[],
        source="manual",
    )
    db.add(record)
    db.commit()

    pgs.apply_draft(
        db,
        user,
        account_id=account.id,
        draft={"taboos": ["新禁区甲", "新禁区乙"]},
    )
    db.refresh(record)

    assert record.taboos == ["新禁区甲", "新禁区乙"]


def test_is_empty_uses_the_same_fields_as_injection(db):
    """注入字段全空时，即使 content promise 有值，也必须视为空定位。"""
    user, account = _account(db)
    record = AccountPositioning(
        user_id=user.id,
        platform_account_id=account.id,
        positioning="",
        audience="",
        promise="关注后能稳定拿到方法",  # 只填了这项，它不进提示词
        main_topics=[],
        taboos=[],
        language_samples=[],
        source="manual",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    assert "promise" not in PROMPT_FIELDS, "前提：promise 不注入"
    assert is_empty(record) is True, (
        "注入字段全空时应视为空定位，否则模型会收到一段空壳并被说成真实情况"
    )
    assert positioning_block(db, user, account.id) == ""


def test_promise_alone_never_produces_a_block(db):
    """即便 is_empty 将来又漏了，block 也不能吐出只有标题行的空壳。"""
    user, account = _account(db)
    record = AccountPositioning(
        user_id=user.id,
        platform_account_id=account.id,
        positioning="",
        audience="",
        promise="只给人看",
        main_topics=[],
        taboos=[],
        language_samples=[],
        source="manual",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    block = positioning_block(db, user, account.id)
    assert block == "", f"不该产出空壳定位：{block!r}"


def test_priority_is_smaller_first_and_only_breaks_ties():
    """分数永远优先；同分时按 priority 升序（1 最优先）。

    这个方向由两件既有事实决定，不是随手选的：

    * ``AccountSkillSetting.priority`` 的默认值是 100，而内置 skill 的
      ``sort_order`` 是 10/20/30/40。若「越大越优先」，一个没被改动过的
      100 会压过所有按 sort_order 排好的内置次序。
    * ``test_account_skill_override.test_account_priority_breaks_ties`` 早就
      约定 ``{first: 999, second: 1}`` 应排出 ``[second, first]``。

    所以界面文案改成「数字越小越优先」，与 ``sort_order`` 同向。
    """
    from backend.app.models import SkillLibraryItem
    from backend.app.services.skill_router_service import rank_rows

    def item(pid, order):
        return SkillLibraryItem(
            id=pid,
            user_id=1,
            slug=f"s{pid}",
            name=f"S{pid}",
            description="",
            module="draft",
            triggers="",
            content_md="# x\n去 AI 味，改写口吻。",
            source="",
            license="",
            enabled=True,
            sort_order=order,
        )

    first, second = item(1, 10), item(2, 10)

    ordered = rank_rows(
        [first, second], "去 AI 味", module="draft", priority_by_id={1: 999, 2: 1}
    )
    assert [e.item.id for e in ordered] == [2, 1]

    # 没有 override 时按 sort_order 升序，不受优先级逻辑影响
    a, b = item(3, 30), item(4, 10)
    ordered = rank_rows([a, b], "去 AI 味", module="draft")
    assert [e.item.id for e in ordered] == [4, 3]


def test_score_outranks_priority():
    """优先级只影响同分；相关度更高的必须排前面，否则等于把内容相关性卖了。"""
    from backend.app.models import SkillLibraryItem
    from backend.app.services.skill_router_service import rank_rows

    def item(pid, body, order=10):
        return SkillLibraryItem(
            id=pid,
            user_id=1,
            slug=f"s{pid}",
            name=f"S{pid}",
            description="",
            module="draft",
            triggers="",
            content_md=body,
            source="",
            license="",
            enabled=True,
            sort_order=order,
        )

    # 1 号内容完全命中，2 号只有一点相关；给 2 号最高优先级也不能越位
    relevant = item(1, "# A\n去 AI 味 改写 口吻 去 AI 味")
    irrelevant = item(2, "# B\n定价 策略")

    ordered = rank_rows(
        [relevant, irrelevant],
        "去 AI 味 改写 口吻",
        module="draft",
        priority_by_id={2: 1},
    )
    assert ordered[0].item.id == 1, "低相关度的 skill 靠优先级挤到了前面"
