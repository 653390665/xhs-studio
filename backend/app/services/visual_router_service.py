"""Deterministic visual intent router for the WorkBuddy visual skills."""

from __future__ import annotations

import re
from typing import Any

EXPERTS: dict[str, dict[str, str]] = {
    "cover": {
        "label": "封面锚点",
        "skill_slug": "wb-xhs-cover-anchor",
        "purpose": "单张 3:4 封面、标题锚点、缩略图可读性",
    },
    "illustration": {
        "label": "正文配图（小黑）",
        "skill_slug": "wb-xhs-xiaohei-illustration",
        "purpose": "16:9 白底手绘认知配图、shot list",
    },
    "material": {
        "label": "材质解释图",
        "skill_slug": "wb-xhs-material-illustration",
        "purpose": "机制图、流程图、图表美化、短标签解释图",
    },
}

_RULES: tuple[tuple[str, str, str], ...] = (
    ("cover", r"封面|首图|标题图|cover", "提到封面或标题锚点"),
    ("illustration", r"正文配图|插图|小黑|16:9|认知图|配图", "提到正文配图或小黑认知图"),
    ("material", r"机制|流程|图表|解释图|结构图|对比图|材质", "提到机制/流程/图表"),
)


def route_visual_experts(
    *,
    title: str,
    body: str = "",
    style: str = "",
) -> dict[str, Any]:
    text = f"{style} {title} {body[:300]}".lower()
    selected: list[dict[str, Any]] = []
    for key, pattern, reason in _RULES:
        if re.search(pattern, text, re.I):
            expert = EXPERTS[key]
            selected.append(
                {
                    "key": key,
                    "label": expert["label"],
                    "skill_slug": expert["skill_slug"],
                    "purpose": expert["purpose"],
                    "reason": reason,
                }
            )
    if not selected:
        for key in ("cover", "illustration"):
            expert = EXPERTS[key]
            selected.append(
                {
                    "key": key,
                    "label": expert["label"],
                    "skill_slug": expert["skill_slug"],
                    "purpose": expert["purpose"],
                    "reason": "默认：先封面，再正文配图",
                }
            )

    # Cover + another expert means a sequence, not a merge.
    sequence = [item["key"] for item in selected]
    return {
        "primary": sequence[0],
        "sequence": sequence,
        "experts": selected,
        "requires_exact_title": "cover" in sequence,
        "boundaries": [
            "封面必须基于真实事实，不把无来源数字放上画面",
            "不复制第三方专属图片、模板或字体",
            "没有图片工具时只交付 brief，不声称已出图",
        ],
    }


__all__ = ["EXPERTS", "route_visual_experts"]
