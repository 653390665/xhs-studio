"""Hypotheses for Excel/office-tip short video.

The AI-tool hook set saturates on Excel content: question openings are 72% in the
target and 67% in the baseline (a genre convention), while story/audience/number
hooks are near zero. These five questions describe what Excel accounts actually
do: a failure scene, a taunt, a time promise, screen-operation steps, and a CTA.
"""

from __future__ import annotations

import re

from backend.app.services.style_hypotheses import Hypothesis
from backend.app.services.writing_signals import content_units

_FAILURE = re.compile(r"(让|叫)你[\s\S]{0,40}(结果|你却|你居然|你上来|你就|你直接)")
_TAUNT = re.compile(r"(你不是说自己精通|那我问你|你要.{0,15}到什么时候|别慌|你是不是|你告诉我)")
_TIME = re.compile(r"(五秒|5秒|十秒|10秒|三秒|3秒|一秒|1秒|一键|快速|秒的活|分分钟)")
_STEPS = re.compile(r"(你先|首先|然后|接着|最后|点击|选择|输入|选中|按一下|点一下)")
_CTA_WORDS = ("点赞", "收藏", "关注", "评论区", "学会了吗", "转发", "双击")


def detect_excel_failure(text: str) -> float:
    """Opens with a failure scene: "让你做 X，结果你做成 Y"."""
    return 1.0 if _FAILURE.search(text or "") else 0.0


def detect_excel_taunt(text: str) -> float:
    """Opens with a taunt/reversal: "你不是说自己精通办公软件吗"."""
    return 1.0 if _TAUNT.search(text or "") else 0.0


def detect_excel_time(text: str) -> float:
    """Promises a time/effort result: "五秒搞定 / 一键 / 快速"."""
    return 1.0 if _TIME.search(text or "") else 0.0


def detect_excel_steps(text: str) -> float:
    """Advances by screen-operation verbs: 点击 / 选择 / 输入 / 你先."""
    return 1.0 if _STEPS.search(text or "") else 0.0


def detect_excel_cta(text: str) -> float:
    """Ends on an operation ask: 点赞 / 收藏 / 关注 / 学会了吗."""
    units = content_units(text or "")
    if not units:
        return 0.0
    return 1.0 if any(word in units[-1] for word in _CTA_WORDS) else 0.0


EXCEL_DETECTORS = {
    "excel_failure": detect_excel_failure,
    "excel_taunt": detect_excel_taunt,
    "excel_time": detect_excel_time,
    "excel_steps": detect_excel_steps,
    "excel_cta": detect_excel_cta,
}

EXCEL_HYPOTHESES: list[Hypothesis] = [
    Hypothesis(
        key="excel_failure",
        claim="开头先演一个失败场景（让你做 X，结果你做成 Y）。",
        source="corpus",
        dimension="开头",
        detector="excel_failure",
        rule="开头先演失败场景：让你做 X，结果你做成 Y，再给出解法。",
        counter_rule="不要用失败场景开场，直接给操作。",
        note="失败场景是 Excel 教学最常见的代入方式；实测目标 63%，基线 42%。",
        tags=("hook",),
    ),
    Hypothesis(
        key="excel_taunt",
        claim="用反问/嘲讽戳观众（「你不是说自己精通办公软件吗」）。",
        source="corpus",
        dimension="开头",
        detector="excel_taunt",
        rule="用一句反问或嘲讽开场（你不是说自己精通…/那我问你），再给解法。",
        counter_rule="不要用反问或嘲讽开场。",
        note="实测目标 46%，基线 6%；两批分别 57%/36%。",
        tags=("hook",),
    ),
    Hypothesis(
        key="excel_time",
        claim="开头报时长/效率承诺（五秒、一键、快速）。",
        source="corpus",
        dimension="开头",
        detector="excel_time",
        rule="开头给时长或效率承诺（五秒搞定/一键完成/快速）。",
        counter_rule="不要报时长承诺，直接讲操作。",
        note="实测目标 24%，基线 14%，差距不够，当前只作设计选择。",
        tags=("hook",),
    ),
    Hypothesis(
        key="excel_steps",
        claim="用屏幕操作动词推进（点击/选择/输入）。",
        source="theory",
        dimension="结构",
        detector="excel_steps",
        rule="用屏幕操作动词（点击/选择/输入/你先）一步步推进。",
        counter_rule="不要用操作动词推进。",
        note="Excel 教学的基本盘；目标 83%，基线 75%。",
        tags=("structure",),
    ),
    Hypothesis(
        key="excel_cta",
        claim="结尾求赞/收藏/关注。",
        source="corpus",
        dimension="收尾",
        detector="excel_cta",
        rule="结尾加一句求赞/收藏/关注（点赞收藏，学会了吗）。",
        counter_rule="结尾不要加 CTA。",
        note="实测目标 83%，基线 64%；两批 90%/76%。",
        tags=("closing", "cta"),
    ),
]

EXCEL_HYPOTHESIS_BY_KEY = {item.key: item for item in EXCEL_HYPOTHESES}

__all__ = [
    "EXCEL_DETECTORS",
    "EXCEL_HYPOTHESES",
    "EXCEL_HYPOTHESIS_BY_KEY",
]
