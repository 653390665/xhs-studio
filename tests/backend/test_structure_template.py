"""结构模板：按开头/中段/结尾的位置拆，而不是按词频。"""
from __future__ import annotations

import pytest

from backend.app.services.structure_template_service import (
    build_structure_template,
    check_structure_coverage,
)
from backend.app.services.style_evidence import CorpusDoc

FAIL = (
    "让你把表格拖上去，结果你拖了半天也没拖上去。你不是说自己精通办公软件吗？那我问你。"
    "你先点击表格，然后选择布局。点赞收藏，学会了吗。#Excel #办公技巧"
)
QUESTION = (
    "为什么你的表格总是对不齐？先选中整列，这个可以用来对齐，这个可以统一宽度。"
    "这个方法的核心是先选区域再调格式。"
)
DIRECT = (
    "今天讲一个 Excel 快速求和的方法。先选中区域，然后按 Alt+=。"
    "这个方法的核心是选中再求和。"
)


def _docs():
    docs = []
    for i in range(3):
        docs.append(CorpusDoc(key=f"f{i}", title=f"失败场景{i} #Excel", body=FAIL))
    for i in range(2):
        docs.append(CorpusDoc(key=f"q{i}", title=f"疑问{i} #办公技巧", body=QUESTION))
    docs.append(CorpusDoc(key="d0", title="直接讲 #Excel", body=DIRECT))
    return docs


def test_opening_body_closing_are_measured_by_position():
    payload = build_structure_template(_docs())

    assert payload["documents"] == 6
    assert payload["opening"][0]["label"] == "失败场景"
    assert payload["opening"][0]["pct"] == 50
    assert payload["body"][0]["label"] == "操作步骤"
    assert payload["closing"][0]["label"] in {"求赞/收藏/关注", "判断/金句"}
    assert payload["skeletons"][0]["pct"] == 50
    # Opening labels are not title formulas; the UI labels them separately.
    assert payload["title_formulas"] == []
    assert any("开头：失败场景（50%）" in line for line in payload["structure"])
    middle = {item["label"]: item["pct"] for item in payload["middle_elements"]}
    assert middle["操作步骤"] == 100
    assert "Excel" in payload["hashtags"]
    assert payload["recommendations"]


def test_template_requires_three_documents():
    with pytest.raises(ValueError):
        build_structure_template(_docs()[:2])


def test_coverage_separates_strict_from_soft_match():
    payload = build_structure_template(_docs())

    strict = check_structure_coverage(FAIL, payload)
    assert strict["coverage"] == 100
    assert strict["soft_coverage"] == 100
    assert strict["skeleton_match"] is True
    assert [item["position"] for item in strict["positions"]] == [
        "opening",
        "body",
        "closing",
    ]
    middle = {item["label"]: item["present"] for item in strict["middle_elements"]}
    assert middle["操作步骤"] is True
    assert 0 <= strict["middle_element_coverage"] <= 100

    # The question opening is the runner-up, so it is a soft match but not a
    # strict one. Reporting only one number would hide that difference.
    soft = check_structure_coverage(QUESTION, payload)
    assert soft["coverage"] < 100
    assert soft["soft_coverage"] == 100
    assert soft["positions"][0]["soft_match"] is True
    assert soft["positions"][0]["strict_match"] is False


def test_problem_opening_beyond_the_narrow_failure_pattern():
    payload = build_structure_template(_docs())
    text = (
        "点了排序，弹窗跳出来一句“此操作要求合并单元格具有相同大小”，"
        "要么勉强排完顺序全乱。\n\n"
        "先选中整列，然后点击取消合并，最后按 Ctrl+Enter 批量填充。"
        "这样就能正常排序。点赞收藏，学会了吗？"
    )

    result = check_structure_coverage(text, payload)

    assert result["positions"][0]["detected"] == "失败场景"
    assert result["positions"][0]["strict_match"] is True


def test_unknown_opening_is_not_silently_called_direct_conclusion():
    payload = build_structure_template(_docs())
    text = (
        "顶部。\n\n"
        "先选中整列，然后点击取消合并，最后按 Ctrl+Enter 批量填充。"
        "这样就能正常排序。点赞收藏，学会了吗？"
    )

    result = check_structure_coverage(text, payload)

    opening = result["positions"][0]
    assert opening["detected"] == "其他/未分类"
    assert opening["strict_match"] is False
    assert opening["confidence"] == 0.0


def test_direct_opening_has_lower_confidence_than_a_rule_match():
    payload = build_structure_template(_docs())
    text = (
        "这个可以一键把表格整理好，建议先收藏。\n\n"
        "先选中整列，然后点击取消合并，最后按 Ctrl+Enter 批量填充。"
        "这样就能正常排序。点赞收藏，学会了吗？"
    )

    result = check_structure_coverage(text, payload)

    opening = result["positions"][0]
    assert opening["detected"] == "直接给结论"
    assert opening["confidence"] == 0.7


def test_coverage_rejects_non_positional_template():
    with pytest.raises(ValueError):
        check_structure_coverage(FAIL, {"structure": ["开头：痛点"]})


def test_trailing_hashtags_are_not_a_closing_move():
    payload = build_structure_template(_docs())
    without_tags = FAIL.split("#Excel")[0]

    with_tags = check_structure_coverage(FAIL, payload)
    without = check_structure_coverage(without_tags, payload)

    assert with_tags["positions"][-1]["detected"] == without["positions"][-1]["detected"]
