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


# ------------------------------------------------ 折行不丢字（实测回归）


def test_wrap_line_never_drops_characters():
    """实测：3 条 × 22 字一页会丢字。折行必须保住每一个字。"""
    from backend.app.services.xhs_card_planner import _wrap_line

    src = "风险要第一时间报出去，越晚说成本越高，还显得在掩盖"
    lines = _wrap_line(src)
    rebuilt = "".join(lines).replace("，", "")
    assert rebuilt == src.replace("，", ""), f"丢字了：{lines}"
    assert all(len(x) <= 18 for x in lines)


def test_wrap_line_splits_on_punctuation_not_mid_word():
    from backend.app.services.xhs_card_planner import _wrap_line

    lines = _wrap_line("这一周实际推进了什么，和原计划差在哪里，需要谁拍板")
    # 每一行都应该以完整的小句结尾（除最后一行）—— 不允许出现「差在 / 哪里」这种裂开
    for ln in lines[:-1]:
        assert ln[-1] in "，,、；;。！？", f"断在了半句：{ln}"


def test_wrap_line_without_punctuation_keeps_one_line():
    """没有标点的句子不硬切 —— 硬切出「需要明 / 确下来」比长一行更糟。

    单行长度由单页字数预算兜底（MAX_CHARS_PER_PAGE）。
    """
    from backend.app.services.xhs_card_planner import _wrap_line

    src = "下一周打算做什么哪一件最优先排需要明确下来"
    lines = _wrap_line(src)
    assert lines == [src], f"无标点不该硬切，实际 {lines}"


def test_paginate_keeps_page_under_char_budget():
    from backend.app.services.xhs_card_planner import _paginate_by_chars

    items = ["风险要第一时间报出去，越晚说成本越高"] * 6      # 6 × 17 = 102 字
    groups = _paginate_by_chars(items, budget_pages=6)
    assert len(groups) >= 2, "102 字应该拆成至少 2 页"
    for g in groups:
        assert sum(len(x) for x in g) <= 60 + 20, "单页字数超预算"


def test_plan_pages_splits_when_page_too_dense():
    """剩余条目超过单页 60 字预算 → 应该拆成两页。

    注意封面会吃掉第一条当副标题，所以这里用 5 条：
    封面 1 条，剩 4 条 × 约 25 字 = 100 字，必须拆两页。
    """
    body = "\n".join(
        [
            "1. 风险要第一时间报出去，越晚说成本越高还显得在掩盖",
            "2. 这一周实际推进了什么和原计划差在哪里需要说清楚",
            "3. 下一周打算做什么哪一件最优先排需要明确下来",
            "4. 有哪些外部依赖还没到位需要谁来推动一下",
            "5. 哪些决定需要现在拍板不然下周就来不及了",
        ]
    )
    pages = plan_pages(title="周报要点", body=body, max_pages=6)
    content = [p for p in pages if p.page_type == "content"]
    assert len(content) >= 2, f"剩余 100 字应该拆页，实际 {len(content)} 个内容页"


def test_page_lines_respect_wrap_limit():
    """有标点的长条目按标点折行；每页总量由分页预算控制。

    这里直接测 _wrap_line：折出来的每一行（除最后一行）都以标点收尾，
    所以不会出现「需要明 / 确下来」这种把词劈开的行。
    """
    from backend.app.services.xhs_card_planner import _wrap_line

    for i in range(1, 6):
        line = f"这是一条需要折行的要点，内容比较长，还得再补一句才到{i}条"
        for out in _wrap_line(line)[:-1]:
            assert out[-1] in "，,、；;。！？", f"断在词中间了：{out}"

    # 通过 plan_pages 出来的行也不应该超长到离谱
    body = "\n".join(
        f"{i}. 这是一条需要折行的要点，内容比较长，还得再补一句才到{i}条"
        for i in range(1, 6)
    )
    for p in plan_pages(title="标题", body=body, max_pages=6):
        for line in p.lines:
            assert len(line) <= 24, f"行太长：{len(line)} 字 {line}"


def test_bullets_are_not_split_before_pagination():
    """分页按逻辑条目算：一条 25 字不能先被折成两行再参与分页。"""
    from backend.app.services.xhs_card_planner import _bullets

    body = "1. 风险要第一时间报出去，越晚说成本越高还显得在掩盖\n2. 第二条"
    items = _bullets(body)
    assert len(items) == 2, f"应该是 2 个逻辑条目，实际 {len(items)}"
    assert len(items[0]) > 18, "第一个条目应该还是原始长度（未折行）"


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
