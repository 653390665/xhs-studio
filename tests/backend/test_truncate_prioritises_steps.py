"""Skill 截断必须优先保住「可执行步骤」，否则方法论等于没进去。

实测：排期 skill 7418 字，`## E — 可执行步骤` 占 1911 字。旧的按长度比例
分配在 2000 字预算下只给 E 段 511 字——步骤在第二条就断了。模型读到的
是「有这篇 skill」，但照做不了。
"""

from __future__ import annotations

import re

from backend.app.services.skill_library_service import truncate_markdown


def _section(text: str, prefix: str) -> str:
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip().startswith(prefix)
            if inside:
                out.append(line)
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


LONG_SKILL = """## R — 原文

> 「先想清楚怎么变现，再做账号。」
""" + "引用说明。" * 40 + """

## I — 方法论骨架

""" + "方法论说明。" * 120 + """

## E — 可执行步骤

1. **列出可售卖资产**
   - 询问用户已有产品、技能、资源、服务、社群、渠道和可投入时间。
   - 完成标准: 至少列出 3 个可能被市场购买或交换的资产。

2. **明确 offer 与信任路径**
   - 写清产品/服务/资源包/咨询/课程/社群是什么。
   - 完成标准: 必须有一个可验证的付款理由或信任资产。

3. **选择主变现路径**
   - 在商单、带货、店铺、咨询、课程、社群、私域转化中选一个主、一个副。
   - 完成标准: 能说清「谁为什么会为我付费」。

## B — 边界

- 用户已经给出明确定位时不要用。
- 失败模式：把「喜欢什么」当成唯一定位依据。
"""


def test_actionable_section_survives_a_tight_budget():
    out = truncate_markdown(LONG_SKILL, 900)

    assert len(out) <= 900
    steps = _section(out, "## E")
    assert steps, "可执行步骤整段丢了"
    # 至少保住前两步和它们的完成标准
    assert "列出可售卖资产" in steps
    assert "明确 offer 与信任路径" in steps
    assert "完成标准" in steps


def test_actionable_section_is_kept_whole_when_it_fits():
    """E 段本身不长时必须整段保留，而不是按比例被削掉一截。"""
    out = truncate_markdown(LONG_SKILL, 900)
    kept = _section(out, "## E")
    original = _section(LONG_SKILL, "## E")

    assert "…" not in kept, "可执行步骤被截断了"
    assert len(kept) >= len(original) - 5, f"E 段只留了 {len(kept)}/{len(original)}"
    assert "选择主变现路径" in kept, "最后一步丢了"


def test_context_sections_are_not_erased():
    """不能为了保住步骤，把「为什么」全删掉。"""
    out = truncate_markdown(LONG_SKILL, 900)
    assert _section(out, "## R"), "原文引用整段丢了"
    assert _section(out, "## B"), "边界整段丢了"


def test_headings_still_all_present():
    out = truncate_markdown(LONG_SKILL, 900)
    heads = [ln for ln in out.splitlines() if ln.startswith("## ")]
    assert len(heads) == 4, heads
