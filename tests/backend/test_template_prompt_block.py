"""结构模板进提示词这一段：不能重复渲染、不能把归档模板当成选中。

两个都出现过：
* 「最常见组合」既是 ``structure`` 的第四行、又被追加一次，提示词里同一句出现两次，
  读起来像「数据反复强调了这个组合」。
* 桥只回 ``ok:true`` 时，前端以为选中成功，实际模板已被删除/归档——用户看着
  「已选 A」，模型拿到的是空骨架。
"""
from __future__ import annotations

from backend.app.services.ai_service import _template_style_block

POSITIONAL = {
    "version": 1,
    "kind": "positional",
    "name": "测试结构",
    "documents": 18,
    "opening": [{"label": "失败场景", "count": 12, "pct": 67}],
    "body": [{"label": "操作步骤", "count": 15, "pct": 83}],
    "closing": [{"label": "求赞/收藏/关注", "count": 14, "pct": 78}],
    "skeletons": [{"label": "失败场景 → 操作步骤 → 求赞/收藏/关注", "count": 11, "pct": 61}],
    "structure": [
        "开头：失败场景（67%）",
        "中段：操作步骤（83%）",
        "结尾：求赞/收藏/关注（78%）",
        "最常见组合：失败场景 → 操作步骤 → 求赞/收藏/关注（61%）",
    ],
}


def test_skeleton_line_is_not_repeated():
    block = _template_style_block(POSITIONAL)
    assert block.count("最常见组合") == 1, block


def test_structure_positions_are_stated():
    block = _template_style_block(POSITIONAL)
    assert "失败场景" in block
    assert "操作步骤" in block
    assert "求赞/收藏/关注" in block
    assert "18 篇" in block


def test_missing_skeleton_line_still_gets_added():
    """Old payloads may not have the 4th structure line; it must still appear."""
    payload = dict(POSITIONAL)
    payload["structure"] = ["开头：失败场景（67%）", "中段：操作步骤（83%）"]
    block = _template_style_block(payload)
    assert "最常见组合" in block


def test_empty_template_renders_nothing():
    assert _template_style_block(None) == ""
    assert _template_style_block({}) == ""
