"""`specific_detail` measured pronouns, not specificity.

Caught by comparing two single-author corpora: Ego (147 posts, personal
narrative) scored 94% while AI产品阿豪 (150 posts, product breakdown) scored 26%.
Reading the misses showed the inversion — 阿豪's posts are full of version
numbers and quotes, Ego's are full of 「我觉得」.

Root cause: ``actor`` (我|他|她|我妈|朋友|…) was in the concrete set, so any
first-person sentence counted as "has a checkable detail". Measured: 61% of Ego's
units hit on actor *alone*, and removing it moved her score 93.9% → 1.4%.

A rule that fires on every first-person sentence discriminates nothing, and this
one had become a hard rule that would be injected into every draft.
"""
from __future__ import annotations

from backend.app.services.style_hypotheses import detect_specific_detail


# --- the pronoun trap -------------------------------------------------------


def test_first_person_opinion_is_not_a_specific_detail():
    """「我觉得…」 contains 我 but nothing checkable."""
    assert detect_specific_detail("我觉得这个就是亲密关系打给我的很大的成长。") == 0.0


def test_pure_pronoun_density_does_not_score():
    text = "他说他很回避。她说她很难过。我觉得他们都是好人。"
    assert detect_specific_detail(text) == 0.0


# --- real detail still counts ----------------------------------------------


def test_number_counts():
    assert detect_specific_detail("底层是 Opus 5.5，只有美区 Pro 能进研究预览。") > 0


def test_time_counts():
    assert detect_specific_detail("上周三我把收藏夹清了一遍。") > 0


def test_place_counts():
    assert detect_specific_detail("那天在公司的会议室里聊了两个小时。") > 0


def test_quote_counts():
    assert detect_specific_detail("他跟我说：「这事我不管了。」") > 0


def test_sensation_counts():
    assert detect_specific_detail("讲到一半我手心全是汗。") > 0


def test_mixed_text_scores_between_zero_and_one():
    text = "我觉得还行。上周三我装了 3 个工具。还是不太顺手。"
    score = detect_specific_detail(text)
    assert 0.0 < score < 1.0


def test_empty_text_is_zero():
    assert detect_specific_detail("") == 0.0
    assert detect_specific_detail("   \n  ") == 0.0


# --- the corpus-level regression -------------------------------------------

EGO_LIKE = ["我觉得他其实是不敢。", "她说她不在乎。", "我妈总是这样。"]
AHU_LIKE = ["底层是 Opus 5.5，只有美区能进预览。", "上周三上线，支持 3 个平台。"]


def test_narrative_pronoun_corpus_no_longer_looks_specific():
    """"94% 具体细节" must not be reproducible from pronouns alone."""
    from backend.app.services.style_evidence import CorpusDoc, evaluate_hypothesis
    from backend.app.services.style_hypotheses import HYPOTHESES

    hypothesis = next(h for h in HYPOTHESES if h.detector == "specific_detail")
    docs = [CorpusDoc(key=f"e{i}", title="", body=t) for i, t in enumerate(EGO_LIKE * 10)]
    result = evaluate_hypothesis(hypothesis, docs)
    assert result["coverage"] < 0.5, "只有人称不该构成硬规则"
    assert result["verdict"] != "hard_rule"


def test_fact_dense_corpus_still_registers():
    from backend.app.services.style_evidence import CorpusDoc, evaluate_hypothesis
    from backend.app.services.style_hypotheses import HYPOTHESES

    hypothesis = next(h for h in HYPOTHESES if h.detector == "specific_detail")
    docs = [CorpusDoc(key=f"a{i}", title="", body=t) for i, t in enumerate(AHU_LIKE * 10)]
    result = evaluate_hypothesis(hypothesis, docs)
    assert result["coverage"] > 0.5, "真正有事实的稿子应该能被识别"
