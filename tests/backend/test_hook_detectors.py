"""Hook / layout detectors: the first attempt silently measured the wrong thing.

Two defects were caught by spot-checking, not by the suite, so they get tests:

1. A title-scoped detector was handed ``"{title}\\n{body}"`` and scored the whole
   string. ``hook_contrast`` reported 93.2% — byte-identical to the body-level
   ``contrast`` — because every hit came from her paragraphs.
2. ``hook_identity`` reused ``viral_analysis.IDENTITY_MARKERS``, a creator /
   e-commerce vocabulary (小白, 打工人, 宝妈). Against a psychology corpus it
   returned 0/147 while the titles plainly address identities
   (「回避型的痛苦」「女人会撒娇」「真正掌握主动权的人」). A word list tuned for one
   track cannot measure another.
"""
from __future__ import annotations

from backend.app.services.style_evidence import DETECTORS, CorpusDoc
from backend.app.services.style_hypotheses import (
    detect_hook_contrast,
    detect_hook_identity,
    detect_hook_number,
    detect_paragraph_rhythm,
)


# --- 1. title-scoped detectors must not read the body -----------------------


def test_hook_contrast_ignores_body_reversal():
    """A reversal in the body must not satisfy a rule about the title."""
    text = "今天聊聊亲密关系\n她不是不爱他，而是不敢爱。"
    assert detect_hook_contrast(text) == 0.0


def test_hook_contrast_reads_the_title_itself():
    text = "反复爱上同一种人，不是宿命，是创伤\n正文可以随便写。"
    assert detect_hook_contrast(text) == 1.0


def test_hook_number_ignores_a_number_in_the_body():
    text = "聊聊工具\n我用过 12 个 AI 工具。"
    assert detect_hook_number(text) == 0.0


def test_hook_number_reads_the_title():
    assert detect_hook_number("5 个 AI 工具，我只留下 2 个\n正文") == 1.0


def test_text_for_detector_gives_title_detectors_the_title():
    """The plumbing that made the bug possible must stay explicit."""
    doc = CorpusDoc(key="x", title="标题党", body="正文在这里")
    assert doc.text_for_detector("hook_number").startswith("标题党")
    # A body rule still must not see the title.
    assert not doc.text_for_detector("contrast").startswith("标题党")


# --- 2. identity markers must not be one-track ------------------------------


def test_identity_marker_recognises_relationship_roles():
    assert detect_hook_identity("回避型的痛苦，只有他们的伴侣知道\n正文") == 1.0
    assert detect_hook_identity("女人会撒娇，幸福好运到\n正文") == 1.0
    assert detect_hook_identity("真正掌握主动权的人，是能感知到自我的人\n正文") == 1.0


def test_identity_marker_still_recognises_the_creator_vocabulary():
    """The original list must keep working — this is an extension, not a swap."""
    assert detect_hook_identity("打工人 5 分钟早餐\n正文") == 1.0
    assert detect_hook_identity("零基础也能学会\n正文") == 1.0


def test_identity_marker_does_not_fire_on_a_plain_statement():
    assert detect_hook_identity("今天天气不错\n正文") == 0.0


# --- 3. paragraph rhythm must measure joined units, not raw lines -----------


def test_paragraph_rhythm_ignores_caption_line_breaks():
    """130 caption lines of 10 chars is not 130 short paragraphs."""
    transcript = "\n".join(["这是一个字幕断行"] * 5)
    # Only 5 joined units → below the 10-unit floor.
    assert detect_paragraph_rhythm(transcript) == 0.0


def test_paragraph_rhythm_fires_on_genuinely_segmented_writing():
    body = "\n".join([f"第{i}段，每段都不长，读起来有节奏感。" for i in range(12)])
    assert detect_paragraph_rhythm(body) == 1.0


# --- 4. every new detector is registered and scoped -------------------------


def test_new_detectors_are_registered():
    for name in (
        "hook_number",
        "hook_question",
        "hook_identity",
        "hook_contrast",
        "hook_emoji",
        "paragraph_rhythm",
        "emoji_use",
        "bullet_layout",
    ):
        assert name in DETECTORS, f"{name} 未注册"


def test_new_detectors_are_pure_over_empty_input():
    """No detector may raise on empty text — the distillation run would die."""
    for name in DETECTORS:
        assert DETECTORS[name]("") >= 0.0, name
        assert DETECTORS[name]("   \n \n") >= 0.0, name
