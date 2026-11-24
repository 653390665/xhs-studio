"""The 爆款模板 must actually shape the generation prompt."""

from __future__ import annotations

from backend.app.services.ai_service import (
    _template_style_block,
    parse_generated_note,
    parse_generated_note_with_tags,
    split_trailing_tags,
)


def test_style_block_is_empty_without_template():
    assert _template_style_block(None) == ""
    assert _template_style_block({}) == ""


def test_style_block_includes_formulas_structure_and_cta():
    template = {
        "title_formulas": ["数字 + 身份 + 结果"],
        "example_titles": ["3 个方法，普通人也能做爆款"],
        "structure": ["开头：制造代入感", "中段：3–5 个要点"],
        "cta_examples": ["你更想先试哪一步？"],
        "keywords": ["咖啡", "通勤"],
        "hashtags": ["咖啡日常"],
        "recommendations": ["正文 300–1200 字"],
    }

    block = _template_style_block(template)

    assert "标题/要点模板" in block
    assert "标题公式" in block
    assert "数字 + 身份 + 结果" in block
    assert "参考标题" in block
    assert "3 个方法" in block
    assert "内容要点/结构" in block
    assert "1. 开头：制造代入感" in block
    assert "2. 中段" in block
    assert "结尾 CTA 参考" in block
    assert "#咖啡日常" in block
    assert "额外要求" in block


def test_style_block_tolerates_partial_templates():
    block = _template_style_block({"title_formulas": ["痛点 + 方案"]})

    assert "标题公式" in block
    assert "内容要点/结构" not in block
    assert "标题/要点模板" in block


def test_positional_template_becomes_per_position_rules():
    template = {
        "kind": "positional",
        "name": "Excel 结构",
        "documents": 46,
        "structure": [
            "开头：失败场景（63%），其次 直接给结论（24%）",
            "中段：操作步骤（83%）",
            "结尾：求赞/收藏/关注（83%）",
            "最常见组合：失败场景 → 操作步骤 → 求赞/收藏/关注（63%）",
        ],
        "opening": [
            {"label": "失败场景", "count": 29, "pct": 63},
            {"label": "直接给结论", "count": 11, "pct": 24},
        ],
        "body": [{"label": "操作步骤", "count": 38, "pct": 83}],
        "closing": [
            {"label": "求赞/收藏/关注", "count": 38, "pct": 83},
            {"label": "判断/金句", "count": 8, "pct": 17},
        ],
        "skeletons": [
            {"label": "失败场景 → 操作步骤 → 求赞/收藏/关注", "count": 29, "pct": 63}
        ],
    }

    block = _template_style_block(template)

    assert "结构模板：Excel 结构" in block
    assert "开头：失败场景（63%）" in block
    assert "第一段直接进入「失败场景」" in block
    assert "中段按「操作步骤」组织" in block
    assert "最后一段落在「求赞/收藏/关注」" in block
    assert "以本模板为准" in block
    assert "禁止照抄示例原句" in block
    assert "标题/要点模板" not in block
    assert "中段深度增强" not in block


def test_positional_template_can_add_optional_middle_depth():
    template = {
        "kind": "positional",
        "name": "Excel 结构",
        "opening": [{"label": "失败场景", "count": 29, "pct": 63}],
        "body": [{"label": "操作步骤", "count": 38, "pct": 83}],
        "closing": [{"label": "求赞/收藏/关注", "count": 38, "pct": 83}],
        "structure": ["开头：失败场景（63%）", "中段：操作步骤（83%）"],
    }

    block = _template_style_block(template, enhance_middle=True)

    assert "中段深度增强" in block
    assert "不是赛道统计" in block
    assert "为什么会出现这个问题" in block
    assert "适用条件" in block
    assert "替代方法" in block


def test_parse_generated_note_splits_labels():
    title, body = parse_generated_note("标题：打工人早餐方案\n正文：\n第一段\n\n第二段")

    assert title == "打工人早餐方案"
    assert body == "第一段\n\n第二段"
    assert "标题：" not in body
    assert "正文：" not in body


def test_parse_generated_note_handles_bold_and_code_fence():
    content = "```markdown\n**标题：** 3 个早餐方案\n**正文：**\n内容一\n内容二\n```"

    title, body = parse_generated_note(content)

    assert title == "3 个早餐方案"
    assert body == "内容一\n内容二"


def test_parse_generated_note_leaves_plain_text_untouched():
    title, body = parse_generated_note("改写结果：爆款标题 / 更适合小红书种草")

    assert title == ""
    assert body == "改写结果：爆款标题 / 更适合小红书种草"


def test_parse_generated_note_drops_duplicated_title_in_body():
    title, body = parse_generated_note("标题：5 分钟早餐\n正文：\n标题：5 分钟早餐\n直接说结论")

    assert title == "5 分钟早餐"
    assert body == "直接说结论"


def test_parse_generated_note_accepts_same_line_body():
    title, body = parse_generated_note("标题：一句话标题\n正文：一句话正文")

    assert title == "一句话标题"
    assert body == "一句话正文"


def test_trailing_tags_move_out_of_body():
    """The tag rubric reads draft.tags, so tags left in the body score 0.

    The generation prompt asks for a trailing tag line, and models comply, so
    every AI draft used to lose the tags dimension.
    """
    body, tags = split_trailing_tags("正文最后一句。\n\n#一人公司 #AI工具 #副业")

    assert body == "正文最后一句。"
    assert tags == ["一人公司", "AI工具", "副业"]


def test_trailing_tags_strip_xhs_topic_suffix():
    body, tags = split_trailing_tags("正文结束。\n#AI搞事业howto[话题] #行业我知道[话题] #ai[话题]")

    assert body == "正文结束。"
    assert tags == ["AI搞事业howto", "行业我知道", "ai"]


def test_tag_mentioned_inside_prose_is_not_stripped():
    text = "我关注了 #AI 这个话题，很受用。"
    body, tags = split_trailing_tags(text)

    assert body == text
    assert tags == []


def test_tags_only_body_is_left_untouched():
    text = "#only #tags #here"
    body, tags = split_trailing_tags(text)

    assert body == text
    assert tags == []


def test_parse_generated_note_with_tags_end_to_end():
    title, body, tags = parse_generated_note_with_tags(
        "标题：5 分钟早餐\n正文：\n直接说结论。\n\n#早餐 #通勤"
    )

    assert title == "5 分钟早餐"
    assert body == "直接说结论。"
    assert tags == ["早餐", "通勤"]
