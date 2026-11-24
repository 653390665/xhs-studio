"""Task-driven skill routing (pure functions, no database)."""

from __future__ import annotations

import io
import zipfile

from backend.app.models import SkillLibraryItem
from backend.app.services.skill_library_service import parse_skill_pack
from backend.app.services.skill_router_service import (
    query_tokens,
    route_rows,
    score_skill,
)


def _item(item_id: int, slug: str, description: str, module: str, content: str = "") -> SkillLibraryItem:
    return SkillLibraryItem(
        id=item_id,
        user_id=1,
        slug=slug,
        name=slug,
        description=description,
        module=module,
        triggers=[],
        content_md=content or description,
        enabled=True,
        sort_order=item_id,
    )


def test_parse_skill_pack_maps_pack_folders_to_modules():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "phuryn-pm-skills-abc/pm-product-strategy/skills/pricing-strategy/SKILL.md",
            "---\nname: pricing-strategy\ndescription: Pricing and packaging.\n---\n# Pricing\n",
        )
        archive.writestr(
            "phuryn-pm-skills-abc/pm-market-research/skills/competitor-analysis/SKILL.md",
            "---\nname: competitor-analysis\ndescription: Compare competitors.\n---\n# Competitors\n",
        )
        archive.writestr("phuryn-pm-skills-abc/LICENSE", "MIT License")

    items = parse_skill_pack(buffer.getvalue(), source="phuryn-pm-skills")
    by_slug = {item["slug"]: item for item in items}

    assert by_slug["pricing-strategy"]["module"] == "persona"
    assert by_slug["competitor-analysis"]["module"] == "benchmark"
    assert all(item["license"] for item in items)


def test_query_tokens_bridges_chinese_intent_to_english():
    tokens = query_tokens("帮我给产品做一次定价")

    assert "pricing" in tokens
    assert "定价" in tokens or "定价"[:2] in tokens


def test_route_rows_picks_pricing_skill_for_pricing_task():
    rows = [
        _item(1, "pricing-strategy", "How to price a SaaS product and package plans.", "persona"),
        _item(2, "hiring-loop", "Interview loop design and hiring scorecards.", "general"),
        _item(3, "cover-anchor", "3:4 封面锚点和缩略图规则。", "visual"),
    ]

    routed = route_rows(rows, "帮我想想产品定价和套餐怎么设计", limit=3)

    assert routed
    assert routed[0].item.slug == "pricing-strategy"
    assert any("定价" in reason or "pricing" in reason.lower() for reason in routed[0].reasons)


def test_route_rows_excludes_visual_outside_visual_module():
    rows = [
        _item(1, "cover-anchor", "封面锚点和缩略图规则。", "visual"),
        _item(2, "pricing-strategy", "Pricing strategy and packaging.", "persona"),
    ]

    text_routed = route_rows(rows, "封面怎么做", module="draft")
    visual_routed = route_rows(rows, "封面怎么做", module="visual")

    assert all(entry.item.module != "visual" for entry in text_routed)
    assert visual_routed and visual_routed[0].item.module == "visual"


def test_route_rows_returns_nothing_for_irrelevant_task():
    rows = [_item(1, "pricing-strategy", "Pricing strategy and packaging.", "persona")]

    assert route_rows(rows, "今天天气怎么样", limit=3) == []


def test_route_rows_respects_limit_and_scores():
    rows = [
        _item(1, "pricing-strategy", "pricing strategy", "persona"),
        _item(2, "pricing-research", "pricing research", "benchmark"),
        _item(3, "pricing-packaging", "pricing packaging", "draft"),
    ]

    routed = route_rows(rows, "pricing", limit=2)

    assert len(routed) == 2
    assert routed[0].score >= routed[1].score


def test_score_skill_prefers_name_match_over_content_match():
    named = _item(1, "pricing-strategy", "A generic guide.", "persona", "nothing here")
    buried = _item(2, "generic-guide", "A generic guide.", "persona", "pricing appears in the body")

    named_score, _ = score_skill(named, "pricing")
    buried_score, _ = score_skill(buried, "pricing")

    assert named_score > buried_score


def test_platform_name_does_not_hijack_routing():
    """The word 小红书 appears in nearly every task and must not decide routing.

    Byte-bigram tokenization turned 小红书 into 小红 + 红书, which matched the
    "小红书定位" trigger of the positioning skill. Ordinary writing tasks then
    received persona methodology instead of the writing skill.
    """
    persona = _item(
        1,
        "wb-xhs-monetization-backsolve",
        "先确定 offer、变现路径和时机，再倒推账号定位。",
        "persona",
        "定位方法论",
    )
    persona.triggers = ["小红书定位", "怎么变现"]

    plain = query_tokens("写一篇早餐主题的小红书笔记，口语化一点")

    assert "小红" not in plain
    assert "红书" not in plain
    score, reasons = score_skill(persona, "写一篇早餐主题的小红书笔记，口语化一点")
    assert score == 0.0, reasons


def test_cover_request_routes_to_visual_skill():
    cover = _item(1, "wb-xhs-cover-anchor", "用事实、模板、锚点和缩略图规则做 3:4 可信封面。", "visual")
    text = _item(2, "wb-xhs-humanize-compliance", "去 AI 味与发布前合规检查。", "draft")

    routed = route_rows([cover, text], "帮我设计封面", module="visual", limit=3)

    assert routed, "a cover request must match a visual skill"
    assert routed[0].item.module == "visual"


# ---------------------------------------------------------------- 口语说法


def _humanize() -> SkillLibraryItem:
    return _item(
        1,
        "wb-xhs-humanize-compliance",
        "去 AI 味与发布前合规检查。",
        "draft",
        "开头不抓人、像 AI 写的、读起来生硬，都可以这样改。",
    )


def test_colloquial_humanize_requests_route_without_exact_trigger():
    """真实用户不会说「执行去 AI 味方法论」。

    「太像 AI 了，改得像人写的」「太像机器写的」「润色一下」在实测里
    只能拿到 0.3–1.6 分，过不了 4.0，路由返回空，助手只好自己发挥。
    """
    skill = _humanize()

    for query in (
        "这篇太像 AI 了，改得像人写的",
        "这篇稿子太像机器写的",
        "润色一下",
        "读起来太生硬，讲人话",
    ):
        routed = route_rows([skill], query, limit=3)
        assert [entry.item.slug for entry in routed] == ["wb-xhs-humanize-compliance"], query


def test_paraphrase_hint_does_not_route_unrelated_skill():
    """口语桥不能把所有 Skill 都拉进来：不相关的仍然 0 命中。"""
    persona = _item(
        1,
        "wb-xhs-monetization-backsolve",
        "先确定 offer、变现路径和时机，再倒推账号定位。",
        "persona",
        "定位方法论",
    )
    persona.triggers = ["小红书定位", "怎么变现"]

    assert route_rows([persona], "这篇太像 AI 了，改得像人写的", limit=3) == []


def test_module_bar_ignores_module_bonus_noise():
    """点名模块只降「相关度」的门槛，不能让「模块匹配 +2」单独过线。

    否则任何模块自己的 Skill 凭 0.3 分的内容命中就能被注入，
    等于门槛失效——实测 persona 在「封面怎么做」下拿到 2.6。
    """
    persona = _item(
        1,
        "wb-xhs-account-profile",
        "账号档案：定位、语气、可信主张。",
        "persona",
        "把定位、语气和个人语言样本写成可复用档案。",
    )

    assert route_rows([persona], "封面怎么做", module="persona", limit=3) == []


def test_rank_rows_keeps_near_misses_for_diagnostics():
    """没到门槛也要能看到最接近的，否则「没命中」只是个黑箱。"""
    from backend.app.services.skill_router_service import rank_rows

    skill = _item(1, "wb-xhs-topic-bank", "七类标题公式与选题库。", "topic", "标题公式")
    ranked = rank_rows([skill], "帮我起个标题")

    assert route_rows([skill], "帮我起个标题") == []
    assert ranked and 0 < ranked[0].score < 4.0


def test_effective_score_matches_the_displayed_threshold():
    """界面上的分数必须和门槛同一刻度。

    `score_skill` 会给自己模块的 Skill 加 2 分「模块匹配」。如果不减掉，
    用户会看到 2.6 分 > 2.5 门槛却没被注入——只会以为路由坏了。
    """
    from backend.app.services.skill_router_service import RoutedSkill, effective_score

    persona = _item(1, "wb-xhs-account-profile", "账号档案。", "persona")
    entry = RoutedSkill(item=persona, score=2.6, reasons=[])

    assert effective_score(entry, "persona") == 0.6
    assert effective_score(entry, "draft") == 2.6
    assert effective_score(entry, None) == 2.6
