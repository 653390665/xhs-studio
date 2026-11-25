"""小红书图文卡片：拆页规则 + 提示词装配 + 接口契约。

为什么守这几条
--------------
1. **分页要装得下**：早期版本把 4 条要点拆成 4 页、每页 1 条，生成出来像半成品。
   现在优先一页装满，只有超预算才拆。
2. **提示词必须写死文字**：实测「只给正文首句 + 无文字」会产出插画或空白纸；
   逐行写死之后 3/5/7/9 行都零错字。这条约束不能被人删掉。
3. **禁止项单独成段**：混在正文里会被模型忽略。
4. **尺寸必须校验**：网关只认 1024x1365 / 1024x1024 / 1365x1024。
"""

from __future__ import annotations

import pytest

from backend.app.services.xhs_card_planner import MAX_LINES_PER_PAGE, plan_pages
from backend.app.services.xhs_card_style import (
    ALLOWED_SIZES,
    DEFAULT_SIZE,
    LAYOUTS,
    STYLES,
    build_page_prompt,
    presets_payload,
    resolve_preset,
)


# ---------------------------------------------------------------- 拆页


def test_bullets_become_one_page_when_they_fit():
    """4 条要点：封面 + 1 个内容页（装 2 条）+ 收尾，不该拆成 4 页。"""
    body = """1. 不是讨好，是降低信息差
2. 不是多汇报，是随时答得上
3. 不是抛问题，是给选项"""
    pages = plan_pages(title="向上管理的三个误区", body=body, max_pages=6)
    content_pages = [p for p in pages if p.page_type == "content"]
    assert len(content_pages) == 1, f"应该只拆 1 个内容页，实际 {len(content_pages)}"


def test_no_page_exceeds_line_cap():
    body = "\n".join(f"{i}. 第 {i} 条要点内容" for i in range(1, 15))
    pages = plan_pages(title="长清单", body=body, max_pages=12)
    for p in pages:
        if p.page_type == "content":
            assert len(p.lines) <= MAX_LINES_PER_PAGE


def test_cover_gets_first_line_as_subtitle():
    body = "第一条\n第二条"
    pages = plan_pages(title="标题", body=body, max_pages=6)
    assert pages[0].page_type == "cover"
    assert pages[0].title == "标题"
    assert pages[0].lines == ["第一条"]


def test_empty_body_still_returns_cover():
    pages = plan_pages(title="只有标题", body="", max_pages=6)
    assert len(pages) >= 1
    assert pages[0].page_type == "cover"


def test_summary_page_has_real_content():
    """收尾页不能是空卡。"""
    pages = plan_pages(title="标题", body="1. 一\n2. 二", max_pages=6)
    summary = [p for p in pages if p.page_type == "summary"]
    if summary:
        assert summary[0].lines, "收尾页没有内容，会生成一张空卡"


def test_markdown_and_hashtags_are_stripped():
    body = "## 小标题\n\n**加粗内容** 正文\n\n#小红书 #副业"
    pages = plan_pages(title="测试", body=body, max_pages=6)
    joined = " ".join(l for p in pages for l in p.lines)
    assert "##" not in joined
    assert "**" not in joined
    assert "#小红书" not in joined


def test_long_sentence_is_trimmed():
    body = "这是一句非常非常长的话，" * 3
    pages = plan_pages(title="测试", body=body, max_pages=6)
    for p in pages:
        for line in p.lines:
            assert len(line) <= 40, f"单行过长会被模型漏字：{line[:50]}"


# ---------------------------------------------------------------- 提示词


def test_prompt_writes_every_line_verbatim():
    prompt = build_page_prompt(
        title="向上管理三件事",
        lines=["主动同步进展", "带方案去沟通"],
        page_type="content",
        style_key="notion",
        layout_key="list",
        index=2,
        total=4,
    )
    assert "「主动同步进展」" in prompt
    assert "「带方案去沟通」" in prompt
    assert "不得修改" in prompt and "不得增删" in prompt
    assert "逐字准确" in prompt


def test_prompt_forbids_rotation_and_extra_text():
    prompt = build_page_prompt(title="标题", lines=["一行"], page_type="cover")
    assert "不得旋转" in prompt or "不得倒置" in prompt
    assert "水印" in prompt


def test_prompt_has_separate_prohibition_section():
    """禁止项要单独成段，混在正文里会被忽略。"""
    prompt = build_page_prompt(
        title="标题", lines=["一行"], style_key="notion", layout_key="list"
    )
    assert "- 禁止：" in prompt or "禁止：" in prompt


def test_prompt_uses_3_4_for_portrait():
    prompt = build_page_prompt(title="标题", lines=[], size="1024x1365")
    assert "3:4" in prompt


def test_prompt_includes_page_type_rules():
    cover = build_page_prompt(title="标题", lines=[], page_type="cover")
    content = build_page_prompt(title="标题", lines=["一行"], page_type="content")
    assert "本页是封面" in cover
    assert "本页是内容页" in content


def test_prompt_respects_style_and_layout():
    notion = build_page_prompt(title="t", lines=["a"], style_key="notion")
    retro = build_page_prompt(title="t", lines=["a"], style_key="retro")
    assert "手绘知识卡" in notion
    assert "复古印刷" in retro
    assert notion != retro


# ---------------------------------------------------------------- 预设


def test_resolve_preset_explicit_wins():
    style, layout = resolve_preset("knowledge-card", "bold", None)
    assert style == "bold", "显式 style 应该盖过 preset"
    assert layout == "dense", "未指定的 layout 仍来自 preset"


def test_resolve_preset_unknown_falls_back():
    style, layout = resolve_preset(None, "不存在的风格", "不存在的布局")
    assert style in STYLES
    assert layout in LAYOUTS


def test_presets_payload_shape():
    payload = presets_payload()
    assert payload["default_size"] == DEFAULT_SIZE
    assert set(payload["sizes"]) == set(ALLOWED_SIZES)
    assert len(payload["styles"]) == len(STYLES)
    assert len(payload["layouts"]) == len(LAYOUTS)
    assert payload["presets"], "预设列表不能为空"
    for item in payload["presets"]:
        assert item["style"] in STYLES
        assert item["layout"] in LAYOUTS


def test_all_styles_have_concrete_palette():
    """风格必须给具体色值或明确的色名，否则提示词等于没说。"""
    for key, style in STYLES.items():
        assert style.palette and len(style.palette) >= 10, f"{key} 缺配色描述"
        assert style.avoid, f"{key} 缺禁止项"


# ---------------------------------------------------------------- 尺寸


def test_size_whitelist():
    assert DEFAULT_SIZE in ALLOWED_SIZES
    assert "1024x1365" in ALLOWED_SIZES
