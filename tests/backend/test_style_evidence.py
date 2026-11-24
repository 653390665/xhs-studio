"""假设 → 取证 → 判定：蒸馏器的核心链路。

These tests pin the method rather than the output, because the output depends on
a corpus. The three thresholds (80/60) and the three verdicsts exist because the
reference corpus produced 93%, 74% and 36% for three different rules; if a future
change collapses them into two buckets, a rule the author only claims becomes a
rule the writer must follow.
"""

from __future__ import annotations

from backend.app.services.style_evidence import (
    HARD_RULE_COVERAGE,
    TENDENCY_COVERAGE,
    VERDICT_DESIGN,
    VERDICT_HARD,
    VERDICT_INSUFFICIENT,
    VERDICT_TENDENCY,
    CorpusDoc,
    evaluate_corpus,
    evaluate_hypothesis,
    rules_for_prompt,
)
from backend.app.services.style_hypotheses import (
    HYPOTHESES,
    HYPOTHESIS_BY_KEY,
    DETECTORS,
    detect_declarative_close,
    detect_result_first,
    detect_specific_detail,
)
from backend.app.services.writing_signals import content_units, join_breath_units

# A post that uses the reversal + mechanism habits.
STRONG = """我今天想讲一个和全网都对抗的观点：你反复受同一种伤，不是运气差，是你主动选了这个情境。
去年冬天我和当时的伴侣爆发过一次冲突，他用了很难听的话攻击我。但我最后没有骂回去，反而看见了他的脆弱。
心理学里有个词叫边界。因为让你痛苦的不是行为本身，是你允许了这个行为。
所以下次对方不回应你，你可以直接说：你这样不回我，我会没有安全感。"""

# Generic advice: no reversal, no mechanism, no specifics.
WEAK = """做自媒体，很多人都会遇到问题。这个问题并不难，关键在于找到适合自己的方法。
首先要明确目标。其次要坚持执行。第三要学会复盘。
很多人做不起来是因为没有坚持。坚持下去一定会有收获。"""


def _docs(texts: list[str]) -> list[CorpusDoc]:
    return [CorpusDoc(key=f"doc{i}", title="标题", body=text) for i, text in enumerate(texts)]


# --- 测量单位 ---------------------------------------------------------------


def test_breath_units_are_joined_back_into_sentences():
    """A transcript arrives as 9-char lines; measuring per line halves the score."""
    transcript = "我今天突然想分享\n就是你怎么看出自己的创伤\n后来我跟我妈聊了\n她说有吃有喝就好了"
    joined = join_breath_units(transcript)
    assert len(joined) < len([line for line in transcript.splitlines() if line.strip()])
    assert all(len(unit) > 0 for unit in joined)


def test_content_units_detects_transcript_vs_prose():
    transcript = "我今天突然想分享\n就是你怎么看出创伤\n后来我跟我妈聊了"
    prose = "去年冬天我和伴侣吵过一次。但我没有骂回去。心理学里叫边界。"
    assert len(content_units(transcript)) < len([line for line in transcript.splitlines() if line.strip()])
    assert len(content_units(prose)) == 3


def test_specific_detail_uses_sentences_not_breath_lines():
    """Measured: 0.49 per breath line vs 0.87 per joined sentence on one corpus."""
    transcript = (
        "去年冬天我和伴侣爆发过一次冲突\n他用了很难听的话攻击我\n但我最后没有骂回去\n"
        "反而看见了他的脆弱"
    )
    score = detect_specific_detail(transcript)
    assert score >= 0.5, "joining breath units must be able to clear the bar"


# --- 判定分档 ---------------------------------------------------------------


def test_high_coverage_becomes_a_hard_rule():
    docs = _docs([STRONG] * 10)
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["contrast"], docs)

    assert item["coverage"] >= HARD_RULE_COVERAGE
    assert item["verdict"] == VERDICT_HARD


def test_mid_coverage_becomes_a_tendency():
    docs = _docs([STRONG] * 7 + [WEAK] * 3)
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["contrast"], docs)

    assert TENDENCY_COVERAGE <= item["coverage"] < HARD_RULE_COVERAGE
    assert item["verdict"] == VERDICT_TENDENCY


def test_low_coverage_becomes_a_design_choice_not_a_rule():
    docs = _docs([WEAK] * 10)
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["contrast"], docs)

    assert item["coverage"] < TENDENCY_COVERAGE
    assert item["verdict"] == VERDICT_DESIGN


def test_too_few_samples_is_not_judged():
    """With two posts, a rule cannot be told apart from a coincidence."""
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["contrast"], _docs([STRONG, WEAK]))

    assert item["total"] == 2
    assert item["verdict"] == VERDICT_INSUFFICIENT
    # Coverage is still reported so the reader can see 1/2 rather than nothing.
    assert item["coverage"] == 0.5


def test_every_hypothesis_has_a_detector():
    """A hypothesis without a detector is an open question, not a silent pass."""
    for item in HYPOTHESES:
        assert item.detector in DETECTORS, f"{item.key} 的检测器不存在"


def test_hypotheses_declare_provenance():
    """theory transfers across subjects; corpus does not. Both must be labelled."""
    assert all(item.source in ("theory", "corpus") for item in HYPOTHESES)
    assert any(item.source == "theory" for item in HYPOTHESES)
    assert any(item.source == "corpus" for item in HYPOTHESES)


# --- 规则只注入该注入的 -------------------------------------------------------


def test_design_choices_are_reported_but_never_injected():
    report = evaluate_corpus(_docs([WEAK] * 10))
    lines = rules_for_prompt(report)

    injected_keys = " ".join(lines)
    design_keys = report["by_verdict"].get(VERDICT_DESIGN, [])
    for key in design_keys:
        rule = HYPOTHESIS_BY_KEY[key].rule
        assert rule not in injected_keys, (
            f"{key} 只是作者自述或设计选择，注入会写成硬要求"
        )


def test_hard_rules_are_injected_with_their_coverage():
    report = evaluate_corpus(_docs([STRONG] * 10))
    lines = rules_for_prompt(report)

    assert lines, "supporting rules must reach the prompt"
    assert all("%" in line for line in lines), "every injected rule carries its coverage"


# --- 语料概况不能静默省略 -----------------------------------------------------


def test_corpus_summary_reports_what_was_not_measured():
    docs = _docs([STRONG] * 5)
    docs.append(CorpusDoc(key="empty", title="空", body=""))
    report = evaluate_corpus(docs)

    assert report["corpus"]["documents"] == 6
    assert report["corpus"]["usable"] == 5, "an empty body must be excluded, and counted"


def test_too_short_body_is_counted_but_not_scored():
    """An 8-character transcript is data, not evidence."""
    docs = _docs([STRONG] * 5)
    docs.append(CorpusDoc(key="tiny", title="t", body="有钱用他没钱用他"))
    report = evaluate_corpus(docs)

    assert report["corpus"]["documents"] == 6
    assert report["corpus"]["usable"] == 5
    assert report["corpus"]["too_short"] == 1
    contrast = next(item for item in report["items"] if item["key"] == "contrast")
    assert contrast["total"] == 5, "短稿不能进入任何一条规则的分母"


def test_corpus_reports_volume_not_only_row_count():
    docs = _docs([STRONG] * 5)
    report = evaluate_corpus(docs)

    assert report["corpus"]["chars"] == sum(len(doc.body.strip()) for doc in docs)
    assert report["corpus"]["chars_median"] > 0


def test_short_post_cannot_satisfy_the_layout_rule():
    """A 40-second clip cannot hold ten 40-character units — the rule stays 0%."""
    from backend.app.services.style_hypotheses import detect_paragraph_rhythm

    short = "\n".join(["这是十来个字的一句口播"] * 5)
    assert detect_paragraph_rhythm(short) == 0.0

    long = "\n".join(["这是十来个字的一句口播"] * 60)
    assert detect_paragraph_rhythm(long) == 1.0


def test_typographic_rules_are_not_scored_on_spoken_transcripts():
    """A transcript can't contain emoji; scoring it 0% invents a habit."""
    docs = [
        CorpusDoc(
            key=f"d{i}",
            title="t",
            body=STRONG,
            meta={"medium": "spoken"},
        )
        for i in range(6)
    ]
    report = evaluate_corpus(docs)
    emoji = next(item for item in report["items"] if item["key"] == "emoji_use")

    assert emoji["total"] == 0
    assert emoji["verdict"] == VERDICT_INSUFFICIENT


def test_zero_measurements_never_become_a_negative_rule():
    """“0% of 0 samples” is not evidence of absence."""
    from backend.app.services.style_evidence import evaluate_hypothesis

    docs = [
        CorpusDoc(key=f"d{i}", title="t", body=STRONG, meta={"medium": "spoken"})
        for i in range(6)
    ]
    item = evaluate_hypothesis(HYPOTHESIS_BY_KEY["emoji_use"], docs)
    assert item["total"] == 0

    report = {
        "items": [item],
        "summary": {},
        "corpus": {},
        "thresholds": {},
        "by_verdict": {},
    }
    assert rules_for_prompt(report) == []


def test_report_separates_baseline_and_negative():
    docs = [
        CorpusDoc(key="b1", title="t", body=STRONG, role="baseline"),
        CorpusDoc(key="n1", title="t", body=WEAK, role="negative"),
    ]
    report = evaluate_corpus(docs)

    assert report["corpus"]["baseline"] == 1
    assert report["corpus"]["negative"] == 1


# --- 具体检测器的行为 ---------------------------------------------------------


def test_result_first_is_scoped_to_the_case_not_the_opening():
    """A first-person opening is fine; the rule is about case ordering."""
    declared_opening = (
        "我今天突然想分享一件事。后来我跟我妈聊起小时候，"
        "我妈说小孩嘛有吃有喝就好了。但最后我发现，我的创伤正来自这句话。"
    )
    assert detect_result_first(declared_opening) == 1.0


def test_result_first_rejects_chronological_case():
    chronological = "后来我跟我妈聊起小时候，她每天忙着做饭。然后我上学，然后我长大，然后我工作。"
    assert detect_result_first(chronological) == 0.0


def test_declarative_close_rejects_trailing_off():
    assert detect_declarative_close("你会变得温柔而有力量") == 1.0
    assert detect_declarative_close("我觉得这个就是") == 0.0
    assert detect_declarative_close("我现在只想") == 0.0
