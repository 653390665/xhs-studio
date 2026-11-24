"""Two detectors measured the transcript, not the author.

Found by distilling the 147-post Ego corpus (single author, spoken-word) and
comparing against the 104-post AI corpus (many authors, written).

1. ``short_units`` split on newlines. Spoken transcripts arrive as ~10-character
   caption lines, so 88% of Ego posts looked like "short sentences". The same rule
   scored 0.000 when measured on ``content_units`` — a sign flip, not a subtlety.
   ``specific_detail`` already used ``content_units``; this one had been missed.

2. ``detect_mechanism`` counted 心理学 / 认知 as evidence of explaining a
   mechanism, so 「今天我想跟大家分享一个心理学的方法」 scored as an explanation.
   That inflated the rule to 87% support.
"""

from __future__ import annotations

from backend.app.services.style_evidence import DETECTORS
from backend.app.services.style_hypotheses import detect_mechanism, detect_short_units
from backend.app.services.writing_signals import content_units


# --- short_units must use the same unit as everything else ------------------


def test_short_units_matches_content_units_on_a_transcript():
    """The exact shape that broke: caption lines, no punctuation."""
    transcript = (
        "第一个就是\n纠集内向\n看起来情绪非常的稳定\n"
        "第二种就是\n阳光型男非常帅\n身材也很好\n健身个子也很高\n"
        "然后很会讲话\n但奇怪的就是\n我对于这一类\n完全不感兴趣"
    )
    units = content_units(transcript)
    expected = sum(1 for u in units if len(u) <= 15) / len(units)

    assert detect_short_units(transcript) == expected


def test_transcript_lines_no_longer_score_as_short_sentences():
    """Per-line this was ~1.0; per content_units the units are joined and long."""
    transcript = (
        "第一个就是\n纠集内向\n看起来情绪非常的稳定\n"
        "第二种就是\n阳光型男非常帅\n身材也很好\n健身个子也很高"
    )
    per_line = sum(1 for l in transcript.splitlines() if len(l) <= 15) / len(
        transcript.splitlines()
    )
    assert per_line >= 0.9, "前提：按行测一定是高分"
    assert detect_short_units(transcript) < 0.5, (
        "按 content_units 测不该把它当成短句风格"
    )


def test_short_units_still_measures_genuinely_short_prose():
    """Real short sentences in punctuated prose must still register."""
    prose = "你好。走吧。别想了。就这样。说完了。"
    assert detect_short_units(prose) == 1.0


def test_short_units_returns_zero_for_empty_text():
    assert detect_short_units("") == 0.0
    assert detect_short_units("   \n  \n") == 0.0


# --- mechanism must require a causal link, not a subject -------------------


def test_topic_words_are_not_mechanism():
    """Naming the field is not explaining anything."""
    for text in (
        "今天我想跟大家分享一个心理学的方法。",
        "我在学心理学之前，是个很暴躁的人。",
        "这个话题和认知有关。",
    ):
        assert detect_mechanism(text) < 0.5, text


def test_real_causal_explanations_still_count():
    for text in (
        "这本质上是一种思维和视野的狭隘。",
        "因为他们并不是在帮助你，他们是在表达自己。",
        "之所以会这样，是因为你从小就不被允许表达情绪。",
        "这导致她后来完全无法信任任何人。",
    ):
        assert detect_mechanism(text) >= 0.5, text


def test_mechanism_detector_is_registered():
    assert "mechanism" in DETECTORS


# --- the corpus-level consequence ------------------------------------------


def _corpus(texts: list[str]):
    from backend.app.services.style_evidence import CorpusDoc

    return [
        CorpusDoc(key=f"d{i}", title="", body=t, role="baseline")
        for i, t in enumerate(texts)
    ]


def test_caption_line_corpus_does_not_produce_a_short_unit_rule():
    """The production symptom: 88% support from caption line breaks alone."""
    from backend.app.services.style_evidence import evaluate_hypothesis
    from backend.app.services.style_hypotheses import HYPOTHESES

    hypothesis = next(h for h in HYPOTHESES if h.detector == "short_units")
    caption_lines = (
        "第一个就是\n纠集内向\n看起来情绪非常的稳定\n"
        "第二种就是\n阳光型男非常帅\n身材也很好\n健身个子也很高"
    )
    docs = _corpus([caption_lines] * 20)

    result = evaluate_hypothesis(hypothesis, docs)

    assert result["coverage"] < 0.5, (
        "字幕断行不该被当成「单句很短」的风格"
    )
    assert result["verdict"] != "hard_rule"


def test_topic_word_corpus_does_not_produce_a_mechanism_rule():
    from backend.app.services.style_evidence import evaluate_hypothesis
    from backend.app.services.style_hypotheses import HYPOTHESES

    hypothesis = next(h for h in HYPOTHESES if h.detector == "mechanism")
    docs = _corpus(["今天我想分享一个心理学的方法，讲认知。"] * 20)

    result = evaluate_hypothesis(hypothesis, docs)

    assert result["coverage"] < 0.5
    assert result["verdict"] != "hard_rule"
