"""Skill 自进化：权重系数与版本命名（纯规则，不调用模型）。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.services.skill_evolution_service import (
    _current_multipliers,
    _next_version,
    _weights_from_multipliers,
)
from backend.app.services.skill_score_service import _craft

NOTE = {
    "title": "我用 3000 块跑通一人公司：3 个 AI 工具和 1 个避坑清单",
    "body": (
        "去年我还在公司上班，现在我一个人做交付。\n\n"
        "第一步，把流程拆成获客、交付、复盘。\n"
        "第二步，用 AI 做初稿，每天省 2 小时。\n"
        "第三步，每月复盘一次，砍掉不赚钱的活。\n\n"
        "真实成本 3000 元，第一个月回款 8000。\n\n"
        "先收藏，评论区告诉我你卡在哪。"
    ),
    "tags": ["一人公司", "AI工具", "宁波", "副业"],
}


def _score(multipliers: dict[str, float] | None = None) -> dict:
    return _craft(
        NOTE["title"],
        NOTE["body"],
        NOTE["tags"],
        "long_text",
        image_count=3,
        media_known=True,
        has_video=False,
        weight_multipliers=multipliers,
    )


def test_weight_multipliers_change_craft_total():
    base = _score()
    boosted = _score({"tags": 1.6, "cover": 1.5, "structure": 0.7})

    assert base["total"] != boosted["total"]
    base_weights = {item["key"]: item["max"] for item in base["dimensions"]}
    boosted_weights = {item["key"]: item["max"] for item in boosted["dimensions"]}
    assert boosted_weights["tags"] > base_weights["tags"]
    assert boosted_weights["structure"] < base_weights["structure"]


def test_current_multipliers_prefer_stored_values_and_clamp():
    skill = SimpleNamespace(
        content_md="",
        structured_json={"weight_multipliers": {"tags": 9.0, "cover": 0.1, "cta": 1.3}},
    )

    multipliers = _current_multipliers(skill)

    assert multipliers["tags"] == 1.8
    assert multipliers["cover"] == 0.6
    assert multipliers["cta"] == 1.3
    assert multipliers["structure"] == 1.0


def test_current_multipliers_fall_back_to_markdown_table():
    skill = SimpleNamespace(
        content_md="| 维度 | 分值 |\n|---|---|\n| 标题钩子 | 30 |\n| 标签 | 5 |\n",
        structured_json={},
    )

    multipliers = _current_multipliers(skill)

    assert multipliers["title_hook"] == 1.5
    assert multipliers["tags"] == 0.6


def test_weights_from_multipliers_sum_to_100():
    weights = _weights_from_multipliers({"tags": 1.3, "structure": 0.8})

    assert round(sum(weights.values()), 1) == 100.0
    assert weights["tags"] > 10
    assert weights["structure"] < 20


def test_next_version_increments_minor():
    assert _next_version("v0.1") == "v0.2-draft"
    assert _next_version("v2.9-draft") == "v2.10-draft"
    assert _next_version("") == "v0.2-draft"
