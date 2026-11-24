"""truncate_markdown must respect its budget as a hard ceiling."""

from __future__ import annotations

import re

from backend.app.services.skill_library_service import truncate_markdown


def _headings(text: str) -> int:
    return len(re.findall(r"^#{1,2} ", text, re.M))


def test_short_text_passes_through_unchanged():
    text = "## 标题\n很短的内容。"
    assert truncate_markdown(text, 1000) == text


def test_budget_is_a_hard_ceiling_even_with_many_sections():
    """50 tiny sections on a 200-char budget must not expand to 700 chars.

    An earlier implementation gave every section a 60-char floor, which tripled
    the output whenever sections outnumbered the budget. Overrunning a prompt
    budget silently crowds out the rest of the instructions.
    """
    text = "\n\n".join(f"## 小节{i}\n内容{i}" for i in range(50))

    out = truncate_markdown(text, 200)

    assert len(out) <= 200, f"budget overrun: {len(out)}"


def test_budget_respected_when_headings_alone_exceed_it():
    text = "\n".join(f"## 很长的标题第{i}节" for i in range(40))

    out = truncate_markdown(text, 200)

    assert len(out) <= 200


def test_all_sections_preserved_when_budget_allows():
    """The original bug: a 9087-char methodology lost its later stages."""
    text = "\n\n".join(
        f"## 第{i}节\n" + "正文内容。" * 60 for i in range(27)
    )
    original_heads = _headings(text)

    out = truncate_markdown(text, 6000)

    assert len(out) <= 6000
    assert _headings(out) == original_heads, "later sections were dropped"
