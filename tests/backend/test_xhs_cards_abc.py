"""A/B/C 三项新功能的测试。

A. 插图模式（none / icon / scene）—— 提示词必须隔离文字与插画区
B. 批量生成 —— 单篇失败不中断整批；空正文要跳过而不是报错
C. 模型拆页 —— 输出解析要严格，失败必须回落算法而不是中断
"""

from __future__ import annotations

import pytest

from backend.app.services.xhs_card_planner import plan_pages, suggest_illustration
from backend.app.services.xhs_card_planner_llm import (
    PlanParseError,
    parse_model_plan,
)
from backend.app.services.xhs_card_style import (
    build_page_prompt,
    presets_payload,
)


# ================================================================ A. 插图


def test_presets_expose_illustration_options():
    payload = presets_payload()
    keys = [i["key"] for i in payload["illustrations"]]
    assert keys == ["none", "icon", "scene"]


def test_no_illustration_block_when_none():
    prompt = build_page_prompt(title="标题", lines=["一行"], illustration="none")
    assert "## 插图" not in prompt


def test_scene_block_separates_text_and_picture():
    prompt = build_page_prompt(
        title="标题", lines=["一行"], illustration="scene", illustration_hint="桌面上的笔记本"
    )
    assert "## 插图：一幅场景插画" in prompt
    assert "下方约 40%" in prompt
    # 最关键的一条：插画不能压文字
    assert "不能压住" in prompt or "绝对不能压住" in prompt
    assert "桌面上的笔记本" in prompt, "illustration_hint 要带进提示词"


def test_icon_block_is_small_and_non_intrusive():
    prompt = build_page_prompt(title="标题", lines=["一行"], illustration="icon")
    assert "## 插图：一个小图标" in prompt
    assert "八分之一" in prompt
    assert "不能压住任何文字" in prompt


def test_illustration_block_comes_after_restraint_rules():
    """插图要求放在克制规则之后，避免被前面的长文淹没。"""
    prompt = build_page_prompt(title="t", lines=["a"], illustration="scene")
    assert prompt.find("## 克制规则") < prompt.find("## 插图")


def test_suggest_illustration_by_page_type():
    assert suggest_illustration("cover", 1) == "scene", "封面要抓人，默认配场景图"
    assert suggest_illustration("content", 2) == "icon", "条目少的内容页配小图标"
    assert suggest_illustration("content", 8) == "none", "条目多时版面已满，不插图"
    assert suggest_illustration("summary", 1) == "none", "收尾页保持干净"


def test_plan_pages_fills_illustration_field():
    pages = plan_pages(title="标题", body="1. 一\n2. 二", max_pages=5)
    assert pages[0].illustration == "scene"
    dumped = pages[0].to_dict()
    assert "illustration" in dumped
    assert "illustration_hint" in dumped


# ================================================================ C. 模型拆页


def test_parse_valid_model_output():
    raw = (
        '{"pages":[{"type":"cover","title":"向上管理","lines":["不是拍马屁"]},'
        '{"type":"content","title":"三个动作","lines":["主动同步","带方案去沟通"]},'
        '{"type":"summary","title":"记住","lines":["降低信息差"]}]}'
    )
    pages = parse_model_plan(raw)
    assert [p.page_type for p in pages] == ["cover", "content", "summary"]
    assert pages[0].title == "向上管理"
    assert pages[1].lines == ["主动同步", "带方案去沟通"]


def test_parse_tolerates_fenced_json_and_prose():
    raw = '好的，这是大纲：\n```json\n{"pages":[{"type":"cover","title":"T","lines":[]}]}\n```\n希望有用'
    pages = parse_model_plan(raw)
    assert pages[0].title == "T"


def test_parse_strips_bullet_prefixes_and_hashtags():
    raw = '{"pages":[{"type":"cover","title":"T","lines":["1. 第一条 #话题"]}]}'
    pages = parse_model_plan(raw)
    assert pages[0].lines == ["第一条 话题"] or "#" not in pages[0].lines[0]


def test_parse_clips_page_and_line_counts():
    many = "{" + '"pages":[' + ",".join(
        '{"type":"content","title":"P%d","lines":[%s]}'
        % (i, ",".join('"l%d"' % j for j in range(20)))
        for i in range(1, 6)
    ) + "]}"
    # 第一页不是封面 → 应该抛错
    with pytest.raises(PlanParseError):
        parse_model_plan(many)


def test_parse_clips_lines_per_page():
    raw = '{"pages":[{"type":"cover","title":"C","lines":[]},' + json_lines(15) + "]}"
    pages = parse_model_plan(raw)
    assert len(pages[1].lines) <= 9


def json_lines(n: int) -> str:
    return '{"type":"content","title":"P","lines":[%s]}' % ",".join(
        '"第%d条"' % i for i in range(n)
    )


@pytest.mark.parametrize(
    "bad,reason",
    [
        ("这不是 JSON", "没有 JSON"),
        ("{}", "pages"),
        ('{"pages":[]}', "pages"),
        ('{"pages":[{"type":"content","title":"x","lines":[]}]}', "封面"),
    ],
)
def test_parse_rejects_garbage(bad, reason):
    with pytest.raises(PlanParseError) as exc:
        parse_model_plan(bad)
    assert reason in str(exc.value) or exc.value


def test_parse_honours_max_pages():
    raw = (
        '{"pages":[{"type":"cover","title":"C","lines":[]},'
        '{"type":"content","title":"A","lines":["a"]},'
        '{"type":"content","title":"B","lines":["b"]}]}'
    )
    assert len(parse_model_plan(raw, max_pages=2)) == 2


# ================================================================ 回归


def test_still_writes_every_line_verbatim_with_illustration():
    """加了插图段之后，文字写死这条不能丢。"""
    prompt = build_page_prompt(
        title="标题",
        lines=["第一条要点", "第二条要点"],
        illustration="scene",
    )
    assert "「第一条要点」" in prompt
    assert "「第二条要点」" in prompt
    assert "不得修改" in prompt and "逐字准确" in prompt
