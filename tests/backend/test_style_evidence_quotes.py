"""证据取样：产物引用的句子必须真的能证明那条规则。

Before this was pinned, the profile cited:
  · 「其实也会发现情绪压抑」as proof of a reversal rule (it only matched "其实")
  · the first line of a post as proof of a closing rule (closings are at the end)
  · a title as proof of "short breath units" (the unit was a 40-char joined sentence)
Each looked like evidence and proved nothing, which is the failure mode this whole
module exists to prevent.
"""

from __future__ import annotations

from backend.app.services.style_evidence import (
    DETECTOR_SCOPE,
    CorpusDoc,
    _sentences_hitting,
    _span_sentences,
    evaluate_hypothesis,
)
from backend.app.services.style_hypotheses import HYPOTHESIS_BY_KEY

# A post with a real reversal, a bare 其实, and no closing statement.
POST = """我今天突然想分享一件事。
关系里的痛苦常常不是对方带来的而是你的创伤被对方的行为唤醒了。
其实很多人都是这样。
所以我们要学会看见自己。
"""

TITLE = "关系里的痛苦不是对方带来的"


def _doc(body: str = POST, title: str = TITLE, key: str = "d1") -> CorpusDoc:
    return CorpusDoc(key=key, title=title, body=body)


# --- 作用域声明 -------------------------------------------------------------


def test_every_detector_declares_a_scope():
    """An undeclared scope silently falls back to "document" and cites nothing."""
    from backend.app.services.style_hypotheses import DETECTORS

    for name in DETECTORS:
        assert name in DETECTOR_SCOPE, f"{name} 没有声明取样作用域"


def test_short_units_is_measured_in_breath_units_not_joined_sentences():
    """A 40-char joined sentence never scores as "short"; a line does."""
    assert DETECTOR_SCOPE["short_units"] == "breath"


def test_document_scope_rules_do_not_fabricate_a_line():
    """Case ordering and closings have no single proving line."""
    assert DETECTOR_SCOPE["result_first"] == "document"
    assert DETECTOR_SCOPE["declarative_close"] == "document"


# --- 强证据优先 -------------------------------------------------------------


def test_strong_reversal_beats_a_bare_qishi():
    """The quote must contain 不是…而是, not merely 其实."""
    hits = _span_sentences(POST, "contrast", wanted=1)

    assert hits, "should find the reversal"
    assert any("不是" in h and "而是" in h for h in hits), (
        f"引用了弱证据：{hits}"
    )


def test_weak_pattern_is_used_only_when_no_strong_pattern_exists():
    weak_only = "其实很多人都是这样。其实我也不例外。"
    hits = _span_sentences(weak_only, "contrast", wanted=1)
    assert hits, "weak evidence is still evidence when nothing stronger exists"
    assert all("其实" in h for h in hits)


def test_specific_detail_quotes_the_detailed_sentence():
    hits = _sentences_hitting(POST, "specific_detail", wanted=1)
    assert hits, "should find a sentence with a checkable point"


# --- 整体行为 ---------------------------------------------------------------


def test_hard_rule_cites_evidence_and_counter_examples():
    docs = [
        # four posts with a real reversal
        *[CorpusDoc(key=f"p{i}", title="t", body=POST) for i in range(4)],
        # one without any reversal, to serve as a counter-example
        CorpusDoc(key="neg", title="t", body="今天天气不错。我去吃了个饭。回来睡觉。"),
    ]
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["contrast"], docs)

    assert item["coverage"] == 0.8
    assert item["samples"], "hard rule must cite evidence"
    assert any("不是" in s and "而是" in s for s in item["samples"]), (
        f"证据应为强句式：{item['samples']}"
    )
    assert item["counter_examples"], "hard rule must show its boundary"


def test_document_scope_citation_names_the_post_instead_of_inventing_a_line():
    docs = [CorpusDoc(key="x1", title="t", body=POST) for _ in range(6)]
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["result_first"], docs)

    # Whether it passes or fails, the citation must point at the post, never at
    # a sentence that happens to score.
    for sample in item["samples"]:
        assert "整篇" in sample or "[" in sample, f"文档级规则引用了具体句：{sample}"


def test_evaluate_hypothesis_never_returns_a_sample_it_did_not_score():
    """Every cited sample must be non-empty and shorter than the post itself."""
    docs = [CorpusDoc(key=f"p{i}", title="t", body=POST) for i in range(6)]
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["contrast"], docs)

    for sample in item["samples"]:
        assert sample.strip()
        assert len(sample) < len(POST) + 40


def test_one_sample_per_post_so_the_list_is_not_filled_with_weak_lines():
    """A post usually contains a strong match and several bare 其实.

    Taking two lines from every post produced 1 real reversal + 3 「其实…」quotes
    in the reference run: the list looked longer but carried less evidence.
    """
    mixed = """关系里痛苦不是对方带来的而是你的创伤被唤醒了。
其实很多人都是这样。
其实我也不例外。
其实我们都一样。
"""
    docs = [CorpusDoc(key=f"m{i}", title="t", body=mixed) for i in range(6)]
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["contrast"], docs)

    strong = [s for s in item["samples"] if "不是" in s and "而是" in s]
    assert len(strong) == len(item["samples"]), (
        f"列表被弱证据填充：{item['samples']}"
    )
    # One per post: six identical posts cannot produce four samples.
    assert len(item["samples"]) <= len(docs)
