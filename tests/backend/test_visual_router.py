"""Visual intent routing for cover / illustration / material experts."""

from __future__ import annotations

from backend.app.services.visual_router_service import route_visual_experts


def test_route_cover_and_illustration_in_sequence():
    result = route_visual_experts(
        title="5 分钟早餐",
        body="先做封面，再配一张正文认知图",
        style="封面 + 正文配图",
    )
    assert result["primary"] == "cover"
    assert result["sequence"] == ["cover", "illustration"]
    assert result["requires_exact_title"] is True


def test_route_material_for_mechanism_diagram():
    result = route_visual_experts(
        title="机制拆解",
        body="把流程画成一张解释图，带短标签",
    )
    assert result["sequence"] == ["material"]
    assert result["experts"][0]["skill_slug"] == "wb-xhs-material-illustration"


def test_route_defaults_to_cover_then_illustration():
    result = route_visual_experts(title="普通标题", body="普通正文")
    assert result["sequence"] == ["cover", "illustration"]
