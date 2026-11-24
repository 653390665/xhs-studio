"""Evidence engine: test each hypothesis against a corpus, keep what survives.

The output is deliberately not a prose description. Every rule carries:

* ``coverage`` — what share of the corpus supports it;
* ``support`` — how many posts support it, out of how many usable;
* ``samples`` — the verbatim lines that made it pass, trimmed;
* ``counter_examples`` — lines that fail it, so the rule has a visible boundary;
* ``verdict`` — 硬规则 / 倾向 / 设计选择 / 未能判定.

Thresholds come from measurement on the ego corpus (154 posts): 「不是…而是」lands
at 71%, 「短句 ≤15 字」at 87%, 「你多于我」at 36%. Those three numbers span the
three verdicts, which is why the cut-offs are 80/60 rather than invented.

A rule whose coverage is under 60% is **not** dropped: it becomes a documented
design choice ("the author says they do this; the corpus says otherwise"). That
is exactly the kind of gap the old pipeline hid.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from backend.app.services.excel_hypotheses import EXCEL_DETECTORS
from backend.app.services.spoken_hypotheses import SPOKEN_DETECTORS
from backend.app.services.style_hypotheses import (
    DETECTORS,
    HYPOTHESES,
    HYPOTHESIS_BY_KEY,
    Hypothesis,
)
from backend.app.services.writing_signals import content_units, split_sentences

# Text-post detectors and spoken-video detectors share one lookup. They stay in
# separate modules because the hypothesis sets answer different questions and are
# selected per corpus, but a rule must be resolvable from its name alone.
_ALL_DETECTORS = {**DETECTORS, **SPOKEN_DETECTORS, **EXCEL_DETECTORS}

# Cut-offs. 80/60 is not arbitrary: the three measured rules from the reference
# corpus land at 87%, 71% and 36%, and they should map to three different
# verdicts, not two.
HARD_RULE_COVERAGE = 0.80
TENDENCY_COVERAGE = 0.60
# Below this a habit is effectively absent from the corpus. Used only to inject a
# negative constraint ("don't do X") when the hypothesis carries a counter_rule.
NEAR_ABSENT = 0.10
# Below this a detector is measuring noise rather than a habit.
MIN_SAMPLES = 5
# Shorter than this is not a writing sample. A sentence or two cannot establish a
# habit, and one 8-character transcript must not shift every rule in a 10-post set.
MIN_USABLE_CHARS = 40
# A habit the control author shares is a property of the genre, not of this
# author. Both thresholds must hold: the control does it often (>=60%) and this
# author is not meaningfully more likely to do it (gap <=15 points).
GENRE_CONVENTION_COVERAGE = 0.60
GENRE_CONVENTION_GAP = 0.15
# A multi-modal trait: the author uses it in at least a quarter of posts and
# meaningfully more often than a same-genre control. Below the tendency
# threshold, but still a signature worth naming ("开头常用问句").
PREFERENCE_COVERAGE = 0.25
PREFERENCE_GAP = 0.15
# A 15-point gap on 27 vs 10 documents is inside the noise: the Wilson interval
# for 44% is [28,63] and for 10% is [2,40]. Require an exact test as well, at an
# exploratory alpha. At n=27 vs 10 the two preferences land at p=0.066 / 0.079.
PREFERENCE_ALPHA = 0.10

VERDICT_HARD = "hard_rule"
VERDICT_TENDENCY = "tendency"
VERDICT_PREFERENCE = "preference"
VERDICT_DESIGN = "design_choice"
VERDICT_INSUFFICIENT = "insufficient"

MAX_SAMPLES = 4
MAX_COUNTER = 3

# Detectors that legitimately read the title. Everything else sees body only —
# a closing rule must never be handed the title, or it measures the title.
#
# The hook detectors below are the exception, and they are why this set exists:
# a rule about "does this author open with a number/identity/contrast hook" is
# *about* the title. Measured on the ego corpus, the analysis module already
# computed these signals (``viral_analysis.analyze_hook``) but the distiller had
# no way to consume them — 11 hypotheses covered 6 dimensions while the hook and
# layout dimensions were computed and thrown away.
_TITLE_DETECTORS: frozenset[str] = frozenset(
    {
        "hook_number",
        "hook_question",
        "hook_identity",
        "hook_contrast",
        "hook_emoji",
    }
)

# Rules that read typography, not language. A spoken transcript cannot contain
# emoji, bullets or numbered line starts — not because the author avoids them,
# but because speech has no characters. Measuring them reported 0% and then
# injected "不要使用任何 emoji" as an instruction, which would strip emoji from
# every draft written in that author's voice.
SPOKEN_UNMEASURABLE: frozenset[str] = frozenset(
    {"emoji_use", "bullet_layout", "inventory_format"}
)


@dataclass
class CorpusDoc:
    """One unit of evidence. ``body`` is the part a rule may read."""

    key: str
    title: str = ""
    body: str = ""
    engagement: int = 0
    role: str = "baseline"
    meta: dict[str, Any] = field(default_factory=dict)

    def text_for_detector(self, detector_name: str | None = None) -> str:
        """The text a detector may read.

        A rule about the body must not receive the title: detectors that look at
        the *end* of a piece would then measure the title, which is a complete
        sentence by construction. ``declarative_close`` reported 95.7% on the AI
        corpus for exactly this reason — after hashtag lines were stripped, the
        "last line" was the title sitting above the body.

        Only title-level rules get the title, and they read it as its own line.
        """
        body = (self.body or "").strip()
        if detector_name in _TITLE_DETECTORS:
            return f"{self.title}\n{body}".strip()
        return body


def _trim(text: str, limit: int = 48) -> str:
    flat = re.sub(r"\s+", " ", (text or "")).strip()
    return flat[:limit] + ("…" if len(flat) > limit else "")


def _verdict(coverage: float, samples: int) -> str:
    if samples < MIN_SAMPLES:
        return VERDICT_INSUFFICIENT
    if coverage >= HARD_RULE_COVERAGE:
        return VERDICT_HARD
    if coverage >= TENDENCY_COVERAGE:
        return VERDICT_TENDENCY
    return VERDICT_DESIGN


def _sentences_hitting(text: str, detector_name: str, wanted: float) -> list[str]:
    """Pick the lines that actually demonstrate (or violate) a rule.

    Three scopes, because calling a document-level detector on single sentences
    returns arbitrary lines:

    * ``sentence`` — the detector works per line (specific detail). Quote the
      lines that individually pass or fail.
    * ``breath`` — the rule is about breath units (short phrasing). The unit is
      the raw line, not a joined sentence, or the detector measures the wrong
      thing (a 40-char joined sentence never scores as "short").
    * ``span`` — the rule is about a phrase inside the text (contrast, mechanism).
      Quote the sentence that contains the match, not a random line.
    * ``document`` — the rule is about the whole piece (case ordering, closing).
      There is no "line that proves it"; return nothing and let the caller cite
      the post itself.
    """
    scope = DETECTOR_SCOPE.get(detector_name, "document")

    if scope == "sentence":
        detector = _ALL_DETECTORS[detector_name]
        hits = []
        for sentence in content_units(text):
            if not sentence:
                continue
            score = detector(sentence)
            if (wanted > 0 and score >= 0.5) or (wanted == 0 and score < 0.5):
                hits.append(sentence)
            if len(hits) >= 2:
                break
        return hits

    if scope == "breath":
        detector = _ALL_DETECTORS[detector_name]
        hits = []
        # Quote the same unit that is scored. This used to split on newlines while
        # the detector had already been changed to score ``content_units``, so the
        # cited "proof" came from a different granularity than the number.
        for unit in content_units(text):
            if len(unit) < 2:
                continue
            score = detector(unit)
            if (wanted > 0 and score >= 0.5) or (wanted == 0 and score < 0.5):
                hits.append(unit)
            if len(hits) >= 2:
                break
        return hits

    if scope == "span":
        return _span_sentences(text, detector_name, wanted)

    return []


# Which sentences prove which rule. A detector absent from this map is treated as
# document-scope: it can score a post but cannot be cited line-by-line.
DETECTOR_SCOPE: dict[str, str] = {
    "short_units": "breath",
    "specific_detail": "sentence",
    "quoted_speech": "span",
    "somatic": "span",
    "contrast": "span",
    "mechanism": "span",
    "inventory_format": "span",
    "transactional_cta": "span",
    "declarative_close": "document",
    "result_first": "document",
    "second_person": "document",
    # Hook rules are proven by the title itself; there is no "line inside the
    # body" that demonstrates them, so they cite the post rather than a sentence.
    "hook_number": "document",
    "hook_question": "document",
    "hook_identity": "document",
    "hook_contrast": "document",
    "hook_emoji": "document",
    # Layout rules are also whole-piece properties.
    "paragraph_rhythm": "document",
    "emoji_use": "document",
    "bullet_layout": "document",
}

_SPAN_PATTERNS: dict[str, tuple[str, ...]] = {
    # Ordered by strength: a full reversal ("不是X而是Y") is far better evidence
    # than a bare "其实". Listing the weak patterns first is how the profile ended
    # up quoting 「其实也会发现情绪压抑」 as proof of a reversal rule.
    "contrast": (
        r".{0,30}不是.{0,25}?而是.{0,40}",
        r".{0,30}不是.{0,14}[，,]\s*是.{0,40}",
        r".{0,30}看似.{0,20}?其实.{0,40}",
        r".{0,30}你以为.{0,20}?其实.{0,40}",
        r".{0,30}反而.{0,40}",
        r".{0,30}其实.{0,40}",
    ),
    "mechanism": (
        r".{0,40}因为.{0,50}",
        r".{0,40}本质上.{0,40}",
        r".{0,40}底层逻辑.{0,40}",
        r".{0,40}心理学.{0,40}",
        r".{0,40}根源.{0,40}",
    ),
    "quoted_speech": (
        r".{0,20}[“\"].{2,60}[”\"].{0,20}",
        r".{0,20}(说[:：]|他说|她说|我妈说|告诉我).{0,50}",
    ),
    "somatic": (
        r".{0,30}(脸红|手抖|心跳|胸口|胃|喘不上|哭|失眠|睡不着|浑身).{0,30}",
    ),
    "inventory_format": (
        r"^\s*(\d+[.、)]|[①②③④⑤⑥⑦⑧⑨⑩]|[-•●])\s*.{0,60}$",
    ),
    "transactional_cta": (
        r".{0,20}(收藏|评论|关注|私信|报名).{0,20}",
    ),
}


def _span_sentences(text: str, detector_name: str, wanted: float) -> list[str]:
    """Sentence-level excerpts around a phrase match, strongest pattern first.

    Iterates patterns in declared order and returns as soon as the strongest
    matching pattern yields evidence: one real reversal beats two bare "其实".
    """
    patterns = _SPAN_PATTERNS.get(detector_name)
    if not patterns:
        return []
    flat = re.sub(r"[ \t]+", " ", text or "")
    for pattern in patterns:
        hits: list[str] = []
        for match in re.finditer(pattern, flat, re.M):
            snippet = match.group(0).strip()
            if wanted > 0 and score_span(detector_name, snippet) >= 0.5:
                hits.append(snippet)
            if len(hits) >= 2:
                break
        if hits:
            return hits
    return []


def score_span(detector_name: str, snippet: str) -> float:
    """Cheap check that a snippet really carries the feature it was found by."""
    detector = _ALL_DETECTORS.get(detector_name)
    if detector is None:
        return 0.0
    try:
        return float(detector(snippet))
    except Exception:  # noqa: BLE001
        return 0.0



def _percentile(values: list[int], q: float) -> int:
    """Nearest-rank percentile for a small sample."""
    ordered = sorted(values)
    if not ordered:
        return 0
    index = int(round(q * (len(ordered) - 1)))
    return ordered[max(0, min(index, len(ordered) - 1))]


def _render_measured_rule(rule: str, counts: list[int]) -> str:
    """Fill ``{median}/{p10}/{p90}`` with this corpus's measurements.

    The layout rule used to hard-code "median 17, p10–p90 5–36" — numbers measured
    on one corpus that then appeared in every other author's profile. A rule may
    state a measured range (an upper bound stops the model from chopping text into
    dozens of fragments), but it must be *that* author's range.
    """
    if "{median}" not in rule:
        return rule
    if not counts:
        return (
            rule.replace("{median}", "—")
            .replace("{p10}", "—")
            .replace("{p90}", "—")
        )
    return rule.format(
        median=_percentile(counts, 0.5),
        p10=_percentile(counts, 0.1),
        p90=_percentile(counts, 0.9),
    )


def evaluate_hypothesis(hypothesis: Hypothesis, docs: Iterable[CorpusDoc]) -> dict[str, Any]:
    """Run one detector over the corpus and produce a verdict."""
    detector = _ALL_DETECTORS.get(hypothesis.detector)
    doc_list = list(docs)

    if detector is None:
        return {
            "key": hypothesis.key,
            "claim": hypothesis.claim,
            "source": hypothesis.source,
            "dimension": hypothesis.dimension,
            "verdict": VERDICT_INSUFFICIENT,
            "coverage": 0.0,
            "support": 0,
            "total": len(doc_list),
            "reason": "该假设没有可执行的检测器，保留为待验证问题。",
            "rule": hypothesis.rule,
            "counter_rule": hypothesis.counter_rule,
            "note": hypothesis.note,
            "samples": [],
            "counter_examples": [],
        }

    scored: list[tuple[CorpusDoc, float]] = []
    for doc in doc_list:
        if (
            doc.meta.get("medium") == "spoken"
            and hypothesis.detector in SPOKEN_UNMEASURABLE
        ):
            # Typography cannot exist in a transcript; skipping keeps the missing
            # measurement out of the denominator instead of scoring it zero.
            continue
        text = doc.text_for_detector(hypothesis.detector)
        if not text.strip():
            continue
        try:
            scored.append((doc, float(detector(text))))
        except Exception:  # noqa: BLE001 - a broken detector must not kill the run
            continue

    total = len(scored)
    unit_counts: list[int] = []
    if "{median}" in hypothesis.rule:
        unit_counts = [
            len(content_units(doc.text_for_detector(hypothesis.detector)))
            for doc, _ in scored
        ]
    rule_text = _render_measured_rule(hypothesis.rule, unit_counts)
    if total == 0:
        return {
            "key": hypothesis.key,
            "claim": hypothesis.claim,
            "source": hypothesis.source,
            "dimension": hypothesis.dimension,
            "verdict": VERDICT_INSUFFICIENT,
            "coverage": 0.0,
            "support": 0,
            "total": 0,
            "reason": "语料为空或全部无法评分。",
            "rule": rule_text,
            "counter_rule": hypothesis.counter_rule,
            "note": hypothesis.note,
            "samples": [],
            "counter_examples": [],
        }

    support = sum(1 for _, value in scored if value >= 0.5)
    coverage = support / total
    verdict = _verdict(coverage, total)
    scope = DETECTOR_SCOPE.get(hypothesis.detector, "document")

    # Evidence: prefer posts whose supporting line is the strongest match, not
    # merely a post that scores 1.0. A post that passes only because of a bare
    # "其实" is weaker evidence than one with a full "不是X而是Y", even though
    # both are binary 1.0 on the detector.
    #
    # One sample per post: taking two lines from the same post fills the list with
    # its weaker sentences (the reference corpus produced 1 strong + 3 bare "其实"
    # quotes because each post contributed two lines).
    scored.sort(key=lambda pair: pair[1], reverse=True)
    candidates: list[tuple[float, str]] = []
    for doc, value in scored:
        if value < 0.5:
            continue
        lines = _sentences_hitting(doc.body, hypothesis.detector, wanted=1)
        if lines:
            best = max(lines, key=lambda line: len(line))
            candidates.append((float(len(best)), best))
        elif scope == "document":
            candidates.append((0.0, f"[{doc.key}] 整篇成立，见原文"))
        else:
            candidates.append((0.0, f"[{doc.key}] {doc.title or doc.body}"))
        if len(candidates) >= MAX_SAMPLES * 3:
            break
    candidates.sort(key=lambda pair: -pair[0])
    samples = [item[1] for item in candidates[:MAX_SAMPLES]]

    counter_examples: list[str] = []
    for doc, value in reversed(scored):
        if value >= 0.5:
            continue
        lines = _sentences_hitting(doc.body, hypothesis.detector, wanted=0)
        if lines:
            counter_examples.extend(_trim(line) for line in lines[:1])
        elif scope == "document":
            counter_examples.append(_trim(f"[{doc.key}] 整篇不成立，见原文"))
        else:
            counter_examples.append(_trim(f"[{doc.key}] {doc.body}"))
        if len(counter_examples) >= MAX_COUNTER:
            break

    reason = {
        VERDICT_HARD: f"{coverage:.0%} 的篇目成立，可写进生成要求。",
        VERDICT_TENDENCY: f"{coverage:.0%} 的篇目成立，作为倾向提示，不作为硬约束。",
        VERDICT_DESIGN: f"仅 {coverage:.0%} 的篇目成立，属作者自述或设计选择，不写进生成要求。",
        # Coverage is still reported: "1/2 supports it" is information, just not
        # enough to act on. Zeroing it out would hide the direction of the data.
        VERDICT_INSUFFICIENT: f"只有 {total} 篇可用（少于 {MIN_SAMPLES} 篇），覆盖率 {coverage:.0%} 仅供参考，不作判定。",
    }[verdict]

    return {
        "key": hypothesis.key,
        "claim": hypothesis.claim,
        "source": hypothesis.source,
        "dimension": hypothesis.dimension,
        "verdict": verdict,
        "coverage": round(coverage, 3),
        "support": support,
        "total": total,
        "reason": reason,
        "rule": rule_text,
        "counter_rule": hypothesis.counter_rule,
        "note": hypothesis.note,
        "samples": list(dict.fromkeys(samples))[:MAX_SAMPLES],
        "counter_examples": list(dict.fromkeys(counter_examples))[:MAX_COUNTER],
    }


def _fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Exact two-sided Fisher test for a 2x2 table.

    Used to keep "preference" from firing on a 15-point gap that is inside the
    noise of a 27-vs-10 comparison. Normal approximation is unreliable at these
    counts (the control has 0/10 in two cells), so the exact test is used.
    """
    import math

    n = a + b + c + d
    if n == 0:
        return 1.0
    row1, col1 = a + b, a + c
    total = math.comb(n, col1)

    def prob(x: int) -> float:
        return math.comb(row1, x) * math.comb(n - row1, col1 - x) / total

    p0 = prob(a)
    lo = max(0, col1 - (n - row1))
    hi = min(row1, col1)
    return sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p0 + 1e-12)


def attach_genre_baseline(
    report: dict[str, Any],
    control_report: dict[str, Any],
    *,
    label: str = "",
) -> dict[str, Any]:
    """Mark rules that a same-genre control author also follows.

    A rule that both authors satisfy at ~80% is a property of the format (short
    spoken tutorials all open with a claim, all say 「你」), not of this author.
    Injecting it makes every profile sound the same, which is the opposite of what
    a style profile is for.

    The comparison stays descriptive: ``control_coverage`` is attached per rule so
    a human can see the gap rather than trust a boolean.
    """
    control_by_key = {
        item["key"]: item for item in control_report.get("items", [])
    }
    flagged = 0
    for item in report.get("items", []):
        control = control_by_key.get(item["key"])
        if control is None:
            continue
        control_coverage = float(control.get("coverage") or 0.0)
        item["control_coverage"] = round(control_coverage, 3)
        item["control_total"] = int(control.get("total") or 0)
        is_convention = bool(
            item["control_total"] >= MIN_SAMPLES
            and control_coverage >= GENRE_CONVENTION_COVERAGE
            # The *main* author must also do it often. Without this, a rule the
            # author almost never uses but the control uses constantly (numbered
            # lists: 15% vs 60%) was labelled "genre convention" and the
            # difference — the interesting part — was hidden.
            and float(item.get("coverage") or 0.0) >= GENRE_CONVENTION_COVERAGE
            and (float(item.get("coverage") or 0.0) - control_coverage)
            <= GENRE_CONVENTION_GAP
        )
        item["genre_convention"] = is_convention
        flagged += int(is_convention)
        coverage = float(item.get("coverage") or 0.0)
        main_total = int(item.get("total") or 0)
        a = int(round(coverage * main_total))
        b = main_total - a
        c = int(round(control_coverage * item["control_total"]))
        d = item["control_total"] - c
        control_p = _fisher_two_sided(a, b, c, d) if main_total and item["control_total"] else 1.0
        item["control_p"] = round(control_p, 4)
        if (
            not is_convention
            and item["verdict"] == VERDICT_DESIGN
            and coverage >= PREFERENCE_COVERAGE
            and coverage - control_coverage >= PREFERENCE_GAP
            and control_p < PREFERENCE_ALPHA
        ):
            # Below the 60% tendency line, but this author does it much more than
            # the genre baseline, and the difference survives an exact test. That
            # is a preference, not a habit: report it as "偏好" and let it shape
            # drafts without becoming a hard requirement.
            item["verdict"] = VERDICT_PREFERENCE
            item["preference"] = True
            # A small control group or a p close to the line is still exploratory:
            # say so instead of presenting it as settled.
            item["preference_confidence"] = (
                "low" if control_p >= 0.05 or item["control_total"] < 15 else "medium"
            )
    report["summary"]["genre_convention"] = flagged
    # Recount verdicts over the rules that are actually about this author. A hard
    # rule that both authors follow is not a hard rule for *this* author; leaving
    # it in the count made the header say "硬规则 1" while the hard-rule section
    # said "没有规则" — the display-vs-fact mismatch this project keeps fixing.
    remaining = [item for item in report.get("items", []) if not item.get("genre_convention")]
    report["summary"].update(
        {
            "hard_rule": sum(1 for i in remaining if i["verdict"] == VERDICT_HARD),
            "tendency": sum(1 for i in remaining if i["verdict"] == VERDICT_TENDENCY),
            "preference": sum(1 for i in remaining if i["verdict"] == VERDICT_PREFERENCE),
            "design_choice": sum(1 for i in remaining if i["verdict"] == VERDICT_DESIGN),
            "insufficient": sum(1 for i in remaining if i["verdict"] == VERDICT_INSUFFICIENT),
        }
    )
    report["genre_baseline"] = {
        "label": label,
        "corpus": control_report.get("corpus", {}),
        "thresholds": {
            "coverage": GENRE_CONVENTION_COVERAGE,
            "gap": GENRE_CONVENTION_GAP,
        },
    }
    return report


def evaluate_corpus(
    docs: Iterable[CorpusDoc],
    *,
    hypotheses: list[Hypothesis] | None = None,
) -> dict[str, Any]:
    """Evaluate every hypothesis and summarise the corpus itself.

    The summary deliberately separates what was measured from what was not: a
    report that silently omits "38% of rows were never collected" is how a thin
    corpus starts looking complete.

    A body shorter than ``MIN_USABLE_CHARS`` is counted but not scored. One
    8-character Douyin transcript ("有钱用他没钱用他") is not a writing sample;
    letting it vote subtracts 10 points from every rule in a 10-post corpus and
    can manufacture a "trend" out of noise.
    """
    doc_list = list(docs)
    usable = [
        doc
        for doc in doc_list
        if len((doc.body or "").strip()) >= MIN_USABLE_CHARS
    ]
    items = [evaluate_hypothesis(item, usable) for item in (hypotheses or HYPOTHESES)]

    by_verdict: dict[str, list[str]] = {}
    for item in items:
        by_verdict.setdefault(item["verdict"], []).append(item["key"])

    return {
        "corpus": {
            "documents": len(doc_list),
            "usable": len(usable),
            "too_short": len(doc_list) - len(usable),
            # Volume, not just row count: ten 40-second Douyin clips are ~2,000
            # characters — less text than two ordinary XHS posts. "9/10 篇可用"
            # looks healthy while the evidence base is an order of magnitude
            # thinner than the corpora these thresholds were calibrated on.
            "chars": sum(len((doc.body or "").strip()) for doc in usable),
            "chars_median": int(
                sorted(len((doc.body or "").strip()) for doc in usable)[len(usable) // 2]
            )
            if usable
            else 0,
            "with_title": sum(1 for doc in usable if doc.title.strip()),
            "baseline": sum(1 for doc in usable if doc.role == "baseline"),
            "negative": sum(1 for doc in usable if doc.role == "negative"),
        },
        "thresholds": {"hard": HARD_RULE_COVERAGE, "tendency": TENDENCY_COVERAGE},
        "items": items,
        "by_verdict": {key: sorted(value) for key, value in by_verdict.items()},
        "summary": {
            "hard_rule": len(by_verdict.get(VERDICT_HARD, [])),
            "tendency": len(by_verdict.get(VERDICT_TENDENCY, [])),
            "preference": len(by_verdict.get(VERDICT_PREFERENCE, [])),
            "design_choice": len(by_verdict.get(VERDICT_DESIGN, [])),
            "insufficient": len(by_verdict.get(VERDICT_INSUFFICIENT, [])),
        },
    }


def rules_for_prompt(report: dict[str, Any]) -> list[str]:
    """Only the rules a writer should follow, each traceable to a coverage figure.

    Hard rules are instructions; tendencies are preferences. Design choices are
    reported but not injected — "you rarely do X" is not a requirement.

    One exception, and it is measured rather than stylistic: when a rule is
    almost *never* true (coverage below ``NEAR_ABSENT``) and it carries a
    ``counter_rule``, that counter rule states a negative constraint
    ("这个作者正文几乎不用 emoji"). Injecting it prevents the model from adding
    a habit the author does not have — the opposite failure of the one this
    guard avoids. Measured on the 阿豪 corpus, `emoji_use` sits at 5% while the
    generated draft used three emoji, landing at the 95th percentile of his own
    posts.
    """
    lines: list[str] = []
    for item in report.get("items", []):
        if item.get("genre_convention"):
            # Both this author and the control do it; it says nothing about
            # *this* author's voice. Report it, never require it.
            continue
        coverage = float(item.get("coverage") or 0.0)
        if item["verdict"] == VERDICT_HARD:
            lines.append(f"- {item['rule']}（{coverage:.0%} 篇目成立）")
        elif item["verdict"] == VERDICT_TENDENCY:
            lines.append(f"- 倾向：{item['rule']}（{coverage:.0%} 篇目成立）")
        elif item["verdict"] == VERDICT_PREFERENCE:
            # A preference is only injected after a later capture batch confirms
            # it. Without that gate, eight exploratory tests at p<0.10 produce a
            # false positive more often than not.
            if item.get("preference_status") != "confirmed":
                continue
            label = "偏好" if item.get("preference_confidence") != "low" else "偏好（探索性）"
            lines.append(
                f"- {label}：{item['rule']}"
                f"（本作者 {coverage:.0%}，对照 {item.get('control_coverage', 0):.0%}，"
                f"p={item.get('control_p', 1):.3f}）"
            )
        elif item["verdict"] == VERDICT_DESIGN and coverage < NEAR_ABSENT and str(
            item.get("counter_rule") or ""
        ).strip():
            lines.append(
                f"- 不要：{item['counter_rule']}（该写法仅 {coverage:.0%} 篇目出现）"
            )
    return lines


def serialize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Same shape as :func:`evaluate_corpus`; exists so callers do not reshape it."""
    return report


__all__ = [
    "HARD_RULE_COVERAGE",
    "TENDENCY_COVERAGE",
    "GENRE_CONVENTION_COVERAGE",
    "GENRE_CONVENTION_GAP",
    "PREFERENCE_COVERAGE",
    "PREFERENCE_GAP",
    "PREFERENCE_ALPHA",
    "VERDICT_HARD",
    "VERDICT_TENDENCY",
    "VERDICT_PREFERENCE",
    "VERDICT_DESIGN",
    "VERDICT_INSUFFICIENT",
    "DETECTOR_SCOPE",
    "CorpusDoc",
    "attach_genre_baseline",
    "evaluate_hypothesis",
    "evaluate_corpus",
    "rules_for_prompt",
    "serialize_report",
]
