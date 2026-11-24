"""Placeholders addressed to the author must never reach the draft.

Real failure (2026-10-29): a generated post contained

    这里需要作者补充自己的经历：你实际用了多久、哪一步最烦、最后留下的是哪个，
    这部分我替不了你。

The prompt itself asked for that phrase ("或写「这里需要作者补充自己的经历」"),
so the model obliged and expanded it. Commit-ready copy turned into a worksheet.

The prompt is fixed, but a prompt instruction is not enforcement — this project
has repeatedly shown that. Hence an output-side guard.
"""
from __future__ import annotations

from backend.app.services.content_sanitizer import (
    PLACEHOLDER_MARKERS,
    strip_author_placeholders,
)

REAL_CASE = (
    "先说结论：别从模型分数开始。\n"
    "这里需要作者补充自己的经历：你实际用了多久、哪一步最烦、最后留下的是哪个，"
    "这部分我替不了你。\n"
    "所以选工具要先分类你的活。\n"
)


# --- removes the real failure ----------------------------------------------


def test_removes_the_actual_failure_sentence():
    cleaned, removed = strip_author_placeholders(REAL_CASE)
    assert "作者补充" not in cleaned
    assert "我替不了你" not in cleaned
    assert removed, "必须报告被删掉的句子"


def test_keeps_the_legitimate_sentences():
    cleaned, _ = strip_author_placeholders(REAL_CASE)
    assert "先说结论" in cleaned
    assert "选工具要先分类你的活" in cleaned


def test_each_marker_is_stripped():
    for marker in PLACEHOLDER_MARKERS:
        text = f"正常的一句话。\n{marker}一些内容。\n另一句正常的话。"
        cleaned, removed = strip_author_placeholders(text)
        assert marker not in cleaned, f"{marker} 未被剔除"
        assert removed, f"{marker} 未被报告"


# --- does not damage normal prose ------------------------------------------


def test_normal_content_is_untouched():
    text = "先说结论。三个场景决定你用哪个工具。最后留个问题：你属于哪一种？"
    cleaned, removed = strip_author_placeholders(text)
    assert cleaned == text
    assert removed == []


def test_talking_about_supplementing_information_is_allowed():
    """The topic alone must not trigger removal — only the meta instruction."""
    text = "写完之后我又补充了两条数据。这条建议来自读者的补充。"
    cleaned, removed = strip_author_placeholders(text)
    assert cleaned == text
    assert removed == []


def test_empty_input():
    assert strip_author_placeholders("") == ("", [])
    assert strip_author_placeholders("   ") == ("   ", [])


def test_cleaned_text_has_no_stray_blank_blocks():
    text = (
        "第一段。\n"
        "这里需要作者补充自己的经历。\n"
        "这里需要你补充。\n"
        "第二段。\n"
    )
    cleaned, removed = strip_author_placeholders(text)
    assert len(removed) == 2
    assert "\n\n\n" not in cleaned
    assert "第一段" in cleaned and "第二段" in cleaned


# --- the prompt itself must not ask for placeholders -----------------------


def test_positioning_prompt_forbids_placeholders():
    """The instruction that caused this must be gone, not merely softened."""
    import inspect

    from backend.app.api import ai as ai_module

    source = inspect.getsource(ai_module._positioning_prompt)
    assert "或写「这里需要作者补充自己的经历」" not in source, "提示词仍在要求模型写占位符"
    assert "禁止占位符" in source
