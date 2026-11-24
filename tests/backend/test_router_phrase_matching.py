"""路由不能靠两个字的中文碎片或跨模块抢活。

Two real defects are pinned here:

1. ``triggers`` were intersected as character bigrams, so the trigger
   「个人IP」 matched the token 「个人」. A topic like
   「15 个人聊 AI 选型」 then routed a positioning skill into a writing task.
2. Any skill scoring above ``MIN_SCORE`` could win a module it does not belong
   to. 「写一篇沙龙复盘」 pulled in 「排期与复盘」 purely because of the word 复盘,
   replacing the writing methodology with a scheduling one.
"""

from __future__ import annotations

from backend.app.models import SkillLibraryItem
from backend.app.services.skill_router_service import route_rows, score_skill


def _item(
    item_id: int,
    name: str,
    module: str,
    *,
    description: str = "",
    triggers: list[str] | None = None,
    content: str = "",
) -> SkillLibraryItem:
    return SkillLibraryItem(
        id=item_id,
        user_id=1,
        slug=f"slug-{item_id}",
        name=name,
        description=description,
        module=module,
        triggers=triggers or [],
        content_md=content or description,
        enabled=True,
        sort_order=item_id,
    )


def test_trigger_bigram_does_not_score_as_phrase():
    """「个人」 inside 「15 个人」 must not count as the trigger 「个人IP」."""
    persona = _item(
        1,
        "变现倒推定位",
        "persona",
        description="先确定 offer 再倒推账号定位。",
        triggers=["个人IP", "小红书定位"],
    )

    score, reasons = score_skill(persona, "第4场宁波沙龙复盘：15个人聊AI选型")

    assert score < 4.0, f"bigram fragment must not clear the threshold: {reasons}"
    assert not any("触发短语" in reason for reason in reasons)


def test_real_trigger_phrase_still_scores():
    """The exact phrase must still be a strong signal."""
    persona = _item(
        1,
        "变现倒推定位",
        "persona",
        description="先确定 offer 再倒推账号定位。",
        triggers=["个人IP", "小红书定位"],
    )

    score, reasons = score_skill(persona, "我要不要做个人IP")

    assert score >= 4.0
    assert any("个人ip" in reason for reason in reasons)


def test_latin_trigger_requires_word_boundary():
    """A short latin trigger must not match inside another word.

    ``ai`` is treated as generic on its own (it appears in nearly every XHS
    topic), so this pins the boundary rule with a longer trigger.
    """
    skill = _item(1, "视觉路由", "visual", triggers=["cover"])

    assert score_skill(skill, "this discovery said nothing")[0] == 0.0
    assert score_skill(skill, "帮我做 cover")[0] > 0.0


def test_generic_latin_trigger_is_ignored():
    """``ai`` alone is too common to route on."""
    skill = _item(1, "视觉路由", "visual", triggers=["ai"])

    score, reasons = score_skill(skill, "用 ai 做封面")

    assert score < 4.0, f"a generic trigger must not clear the threshold: {reasons}"
    assert not any("触发短语" in reason for reason in reasons)


def test_same_module_wins_over_foreign_word_match():
    """A writing task must not receive the scheduling skill."""
    draft_skill = _item(
        1,
        "去 AI 味与发布检查",
        "draft",
        description="改稿与发布前检查。",
        triggers=["去 AI 味"],
    )
    schedule_skill = _item(
        2,
        "排期与复盘",
        "schedule",
        description="排期、内容库存与周复盘。",
        triggers=["排期", "复盘"],
    )

    routed = route_rows(
        [draft_skill, schedule_skill],
        "第4场宁波沙龙复盘：15个人聊AI选型",
        module="draft",
        limit=3,
    )

    assert all(entry.item.module == "draft" for entry in routed), [
        (entry.item.name, entry.reasons) for entry in routed
    ]


def test_foreign_skill_can_join_on_explicit_phrase():
    """Explicitly asking for a foreign discipline still allows the join."""
    draft_skill = _item(
        1,
        "去 AI 味与发布检查",
        "draft",
        description="改稿与发布前检查。",
        triggers=["去 AI 味"],
    )
    schedule_skill = _item(
        2,
        "排期与复盘",
        "schedule",
        description="排期、内容库存与周复盘。",
        triggers=["排期"],
    )

    routed = route_rows(
        [draft_skill, schedule_skill],
        "帮我做排期，顺便给草稿去AI味",
        module="draft",
        limit=3,
    )

    names = [entry.item.name for entry in routed]
    assert "排期与复盘" in names, names
    assert "去 AI 味与发布检查" in names, "the draft skill must still be present"


def test_module_without_own_match_returns_nothing():
    """An owned-but-unmatched module must not be answered by a foreign skill."""
    schedule_skill = _item(
        1, "排期与复盘", "schedule", description="排期与周复盘。", triggers=["排期"]
    )
    draft_skill = _item(
        2, "去 AI 味与发布检查", "draft", description="改稿。", triggers=["去 AI 味"]
    )

    routed = route_rows(
        [schedule_skill, draft_skill],
        "帮我做排期",
        module="schedule",
        limit=3,
    )

    assert [entry.item.name for entry in routed] == ["排期与复盘"]


def test_visual_module_still_isolated():
    """Visual skills must not leak into text modules."""
    cover = _item(1, "封面锚点", "visual", description="3:4 封面锚点。", triggers=["封面"])
    draft = _item(2, "去 AI 味与发布检查", "draft", description="改稿。")

    routed = route_rows([cover, draft], "帮我设计封面", module="draft", limit=3)

    assert all(entry.item.module != "visual" for entry in routed)
