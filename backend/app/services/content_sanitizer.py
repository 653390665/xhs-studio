"""生成结果里混入了「给作者看的提示语」，必须拦住。

2026-10-29 实测：一篇本该直接发布的稿子里出现

    这里需要作者补充自己的经历：你实际用了多久、哪一步最烦、最后留下的是哪个，
    这部分我替不了你。

根因在提示词本身：``_positioning_prompt`` 在定位为空时写了
「或写『这里需要作者补充自己的经历』」——这是给**人**看的占位说明，
却被写成了模型的输出要求，于是模型照做，还自行扩写。

提示词层面已改（明确禁止输出任何提示语/占位符），但**指令不等于强制**。
本项目已经反复证明：只写在提示词里的约束，会在某一次生成里失效。
所以再加一道输出侧检查，把整句剔除。

剔除而不是整篇失败：一句话有问题，不该让全文报废；但必须可观测，
调用方会收到 ``stripped`` 标记。
"""
from __future__ import annotations

import re

__all__ = ["PLACEHOLDER_MARKERS", "strip_author_placeholders"]

# 指向「作者需要自己补充」的元话语。只保留明确的、几乎不可能出现在正常行文里的说法，
# 避免误删正常内容（例如正文里真的在讲「补充经历」这件事）。
PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "这里需要作者补充",
    "需要作者补充",
    "作者补充自己的经历",
    "这部分我替不了你",
    "这部分需要你补充",
    "这里需要你补充",
    "此处需要补充",
    "需要你自行补充",
    "建议补充自己的",
    "请补充你的真实",
    "（作者补充）",
    "(作者补充)",
    "【待补充】",
    "【需补充】",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?\n])")


def strip_author_placeholders(text: str) -> tuple[str, list[str]]:
    """Remove sentences that tell the author to fill something in.

    Returns the cleaned text and the removed sentences, so the caller can report
    what happened instead of silently changing the draft.
    """
    raw = text or ""
    if not raw.strip():
        return raw, []

    removed: list[str] = []
    kept: list[str] = []
    for chunk in _SENTENCE_SPLIT.split(raw):
        if not chunk:
            continue
        if any(marker in chunk for marker in PLACEHOLDER_MARKERS):
            removed.append(chunk.strip())
            continue
        kept.append(chunk)

    cleaned = "".join(kept)
    # 删句可能留下连续空行，收一下，但不改变段落结构以外的内容。
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, removed
