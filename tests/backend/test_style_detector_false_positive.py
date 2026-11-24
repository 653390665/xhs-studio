"""A style detector that could not fail.

``declarative_close`` scored 75/75 = 100% on the 104-note AI corpus, and 100% was
about to be injected into every draft as a hard rule. Four separate reasons:

1. The last line of a real note is ``#AI搞学习howto[话题]# #AI工具[话题]#`` — metadata
   that never ends on a particle and is always longer than six characters.
2. ``CorpusDoc.text_for_detector`` put the *title* on the first line, so after
   the tags were stripped the "last line" was the title — a complete sentence by
   construction. Still 95.7%.
3. ``_strip_trailing_tags`` required ``count("#") >= 2``, so a single-tag line
   survived. Zero-width characters between tags made lines fail the "leftover is
   punctuation" test too.
4. Even with clean text, the detector only asked "is the last line a complete
   sentence" — which nearly every post satisfies. That is not the hypothesis.
   The hypothesis is "the author lands a judgement", so the test now requires an
   asserting word and rejects thanks/disclaimers.

After all four, the same corpus reports 30.4% instead of 100%.
"""

from __future__ import annotations

from backend.app.services.style_evidence import DETECTORS, CorpusDoc, evaluate_hypothesis
from backend.app.services.style_hypotheses import HYPOTHESES, detect_declarative_close
from backend.app.services.writing_signals import _is_tag_line, _strip_trailing_tags


# --- the detector measures a closing, not a grammatical sentence ------------


def test_a_plain_complete_sentence_is_not_a_closing():
    """Almost every post ends with a sentence. That cannot be the feature."""
    assert detect_declarative_close("第一行正文内容。\n今天天气不错。") == 0.0


def test_an_asserting_close_scores_one():
    for closing in (
        "记住，先动手再谈方法。",
        "这件事其实没那么复杂。",
        "先动手才是唯一的路。",
        "所以你要先动手，别只是收藏。",
    ):
        assert detect_declarative_close(f"第一行正文内容。\n{closing}") == 1.0, closing


def test_a_close_that_trails_off_scores_zero():
    assert detect_declarative_close("第一行正文内容。\n我觉得这个就是") == 0.0


def test_thanks_and_disclaimers_are_not_closings():
    for line in ("感谢@小明的分享", "谢谢大家", "（本视频不含任何平台推荐）"):
        assert detect_declarative_close(f"第一行正文内容。\n{line}") == 0.0, line


# --- the tag line must never be the measured line ---------------------------


def test_trailing_tag_lines_do_not_rescue_a_trailing_off_close():
    body = "第一行正文内容。\n我觉得这个就是\n#AI[话题]# #工具[话题]# #副业[话题]#"
    assert detect_declarative_close(body) == 0.0


def test_a_single_tag_line_does_not_count_as_a_closing():
    """``count("#") >= 2`` used to let one-tag lines through."""
    assert detect_declarative_close("第一行正文内容。\n我觉得这个就是\n#AI[话题]") == 0.0


def test_tag_only_body_has_no_closing_at_all():
    assert detect_declarative_close("#AI[话题]# #工具[话题]# #副业[话题]#") == 0.0


def test_zero_width_characters_do_not_hide_a_tag_line():
    """XHS bodies interleave ``\\u200b`` between tags."""
    body = "第一行正文内容。\n我觉得这个就是\n#AI[话题]#\u200b #工具[话题]#\u200b"
    assert detect_declarative_close(body) == 0.0


def test_bare_bullet_after_stripping_is_not_a_close():
    assert detect_declarative_close("第一行正文内容。\n第二行。\n•") == 0.0


# --- tag-line detection itself ---------------------------------------------


def test_tag_line_recognition():
    assert _is_tag_line("#AI[话题]")
    assert _is_tag_line("#AI[话题]# #工具[话题]#")
    assert _is_tag_line("#AI[话题]#\u200b #工具[话题]#")
    assert not _is_tag_line("这是一句真正的正文，虽然带 # 号")


def test_trailing_tag_lines_are_removed():
    text = "正文一\n正文二\n#A[话题]#\n#B[话题]# #C[话题]#"
    assert _strip_trailing_tags(text) == "正文一\n正文二"


# --- the title must not be read as the closing ------------------------------


def test_title_is_not_handed_to_a_body_detector():
    doc = CorpusDoc(
        key="k",
        title="一个标题本身就是完整句子，其实很值得一看",
        body="正文第一行\n我觉得这个就是\n#tag[话题]#",
    )
    assert detect_declarative_close(doc.text_for_detector("declarative_close")) == 0.0
    assert "标题" not in doc.text_for_detector("declarative_close")


def test_detector_receives_body_only():
    doc = CorpusDoc(key="k", title="标题文字", body="正文文字")
    assert doc.text_for_detector("declarative_close") == "正文文字"


# --- the corpus-level consequence -------------------------------------------


def _hypothesis():
    return next(item for item in HYPOTHESES if item.key == "declarative_close")


def _corpus(closing: str, n: int = 20) -> list[CorpusDoc]:
    return [
        CorpusDoc(
            key=f"n{i}",
            title=f"标题 {i}",
            body=f"正文内容 {i}。\n{closing}",
            role="baseline" if i % 2 else "negative",
        )
        for i in range(n)
    ]


def test_tag_only_corpus_reports_zero_support():
    """The production symptom: 69/69 support from notes that end in hashtags."""
    docs = _corpus("我觉得这个就是\n#AI[话题]# #工具[话题]# #副业[话题]#")
    result = evaluate_hypothesis(_hypothesis(), docs)

    assert result["coverage"] == 0.0
    assert result["verdict"] != "hard_rule"


def test_a_corpus_of_plain_sentences_reports_zero_support():
    """Ending every post with an ordinary sentence is not a style finding."""
    docs = _corpus("今天天气不错。")
    result = evaluate_hypothesis(_hypothesis(), docs)

    assert result["coverage"] == 0.0
    assert result["verdict"] != "hard_rule"


def test_real_assertions_still_produce_a_hard_rule():
    """The fix must not make the detector unable to ever pass."""
    docs = _corpus("记住，先动手再谈方法。")
    result = evaluate_hypothesis(_hypothesis(), docs)

    assert result["coverage"] == 1.0
    assert result["verdict"] == "hard_rule"


def test_partial_support_lands_below_the_hard_threshold():
    """15/20 must not be promoted to a hard rule."""
    docs = _corpus("记住，先动手再谈方法。", n=15) + _corpus("今天天气不错。", n=5)
    docs = [
        CorpusDoc(key=f"p{i}", title=f"t{i}", body=d.body, role=d.role)
        for i, d in enumerate(docs)
    ]
    result = evaluate_hypothesis(_hypothesis(), docs)

    assert result["coverage"] == 0.75
    assert result["verdict"] in ("tendency", "design_choice")


def test_declarative_close_is_registered_for_evaluation():
    assert "declarative_close" in DETECTORS
