"""`declarative_close` must measure the closing, not the line breaks.

The defect: the detector took the last *physical line*. A spoken transcript
arrives as ~10-character caption lines, so "你的性魅力" / "也就开始了" became the
"last line" and a complete assertion was rejected as a fragment. Measured on the
two single-author corpora before the fix:

    Ego  (147 posts, transcript)  38%
    阿豪  (150 posts, prose)      70%

That 32-point gap is formatting, not writing.

A second, related bug surfaced here: a note often ends with a topic-tag block
that has no terminal punctuation, so it becomes the final "sentence". Stripping
the tags left an empty string and the real closing one unit earlier.
"""
from __future__ import annotations

from backend.app.services.style_hypotheses import detect_declarative_close


# --- transcripts: breath-separated lines ------------------------------------


def test_breath_split_transcript_counts_as_a_closing():
    """The exact shape that scored 0: a sentence broken across caption lines."""
    transcript = (
        "你看见你们两个之间\n"
        "有一条清晰的边界线\n"
        "那恭喜你\n"
        "那一刻\n"
        "你的独立自我诞生了\n"
        "最后\n"
        "你会变得温柔而有力量"
    )
    assert detect_declarative_close(transcript) == 1.0


def test_transcript_ending_mid_thought_still_fails():
    transcript = (
        "我先说说我的观察\n"
        "很多人其实不是不会表达\n"
        "而是因为"
    )
    assert detect_declarative_close(transcript) == 0.0


# --- prose ------------------------------------------------------------------


def test_punctuated_prose_closing_still_works():
    assert detect_declarative_close("前面说了很多。真正重要的就是，你得先动手。") == 1.0


def test_thanks_and_disclaimers_are_not_closings():
    assert detect_declarative_close("前面讲了方法。感谢@小王 的分享。") == 0.0
    assert detect_declarative_close("正文若干。（本视频不含任何平台推荐）") == 0.0


def test_trailing_off_is_not_a_closing():
    assert detect_declarative_close("写了很多内容。所以我") == 0.0


# --- the tag-block trap -----------------------------------------------------


def test_trailing_topic_tags_do_not_hide_the_closing():
    """Tags form a final punctuation-less 'sentence'; the close is one unit back."""
    text = (
        "这件事我讲了很久。"
        "先想明白自己要的是把内容存好，还是把记忆养起来——想清楚了，后面就会判断了。"
        "#AI工具[话题]# #人工智能[话题]# #效率工具[话题]#"
    )
    assert detect_declarative_close(text) == 1.0


def test_tag_only_body_is_not_a_closing():
    assert detect_declarative_close("#AI工具[话题]# #人工智能[话题]#") == 0.0


def test_empty_input_is_zero():
    assert detect_declarative_close("") == 0.0
    assert detect_declarative_close("   \n \n") == 0.0


# --- the formatting-invariance property ------------------------------------


def test_same_sentence_scores_the_same_whether_split_or_not():
    """Line breaks are an artefact of the source; they must not change the result."""
    one_line = "那恭喜你，你的独立自我诞生了，你的性魅力也就开始了。"
    breath_split = "那恭喜你\n你的独立自我诞生了\n你的性魅力也就开始了"
    assert detect_declarative_close(one_line) == detect_declarative_close(breath_split)


# --- known limitation -------------------------------------------------------


def test_asserting_word_whitelist_still_rejects_some_real_closings():
    """Documented, not fixed.

    Removing the whitelist was tried: coverage became 92–93% on *both* corpora,
    which means the rule stopped distinguishing one author from another. A
    convention everyone follows proves nothing about a single writer. Fixing
    this properly needs a semantic judgement, not a longer word list.
    """
    assert detect_declarative_close("前面说了很多。现在开始干活。") == 0.0
