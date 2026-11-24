"""Methodology hypotheses: what to look for before looking at the data.

Why a library instead of asking the model to "find patterns"
------------------------------------------------------------
A model asked to summarise a corpus returns what the corpus obviously contains:
average sentence length, frequent words, top hashtags. That is description, not
methodology, and it cannot be checked — there is no claim to be wrong about.

An explicit hypothesis can be checked. "Short breath units correlate with
retention" is either supported by 86% of this author's posts or it is not. The
library makes the claim first, then the corpus gets to overrule it.

Provenance matters as much as content
-------------------------------------
Each hypothesis carries ``source``:

* ``theory`` — a transferable mechanism (narrative structure, contrast, concrete
  detail). It should hold across subjects; if it fails on a new corpus that is a
  finding about the subject, not an error in the rule.
* ``corpus`` — a parameter observed in a specific corpus (this author writes 9
  breath units per line). It does not transfer and must be re-measured.

Without that label, a distilled profile silently mixes "people always respond to
concreteness" with "this person happens to use commas like this", and the next
subject inherits the wrong half.

Each hypothesis declares ``detector``: the key of a checkable signal implemented
in :mod:`backend.app.services.writing_signals` (or a local one below). A
hypothesis with no detector stays in the library as an open question rather than
becoming a rule nobody can verify.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.app.services.writing_signals import (
    _strip_trailing_tags,
    closing_moves,
    content_units,
    evidence_signals,
    strip_publish_section,
)

# Topic tags written inline at the end of a line: ``#AI工具[话题]#`` / ``#AI工具``.
# Whole tag-only lines are dropped by ``_strip_trailing_tags``; this handles the
# common case where the last sentence and its tags share a line.
_INLINE_TAG = re.compile(r"#[^#\s\[\]]{1,30}(?:\[话题\])?#?")


@dataclass(frozen=True)
class Hypothesis:
    key: str
    claim: str
    source: str  # theory | corpus
    dimension: str
    detector: str
    rule: str
    """What the rule says when supported, phrased as an instruction."""
    counter_rule: str = ""
    """What to do when the corpus contradicts it. Empty means "just report it"."""
    note: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


# --- Detectors ---------------------------------------------------------------
# Each returns, per text, a number. The aggregation step turns a list of numbers
# into a coverage value and a verdict. A detector must be pure and cheap so the
# same code path can run over 150 posts without a model call.


def detect_short_units(text: str) -> float:
    """Share of units at or under 15 characters — measured on ``content_units``.

    ``content_units`` already decides whether a text is punctuated prose or an
    unpunctuated transcript, and joins transcript breath lines back into sentences
    before measuring. ``specific_detail`` uses it; this detector used to call
    ``splitlines()`` directly and skip that guard, which made it measure the
    transcript's line breaks instead of the author's phrasing.

    The effect is not subtle. On the 147-post Ego corpus the same rule scored 0.900
    per raw line and 0.000 per ``content_units`` — 88% "supported" versus a flat
    contradiction. A rule that flips sign when the splitting changes is not
    measuring the writing.
    """
    units = content_units(text)
    if not units:
        return 0.0
    return sum(1 for unit in units if len(unit) <= 15) / len(units)


def detect_contrast(text: str) -> float:
    """Whether the text uses a reversal (不是X而是Y / 反而 / 其实)."""
    compact = re.sub(r"\s", "", text or "")
    patterns = (
        r"不是.{0,25}?而是",
        r"不是.{0,14}[，,]\s*是",
        r"反而",
        r"其实",
        r"看似.{0,20}?其实",
        r"你以为.{0,20}?其实",
    )
    return 1.0 if any(re.search(pattern, compact) for pattern in patterns) else 0.0


def detect_result_first(text: str) -> float:
    """Whether the *case* opens on the outcome rather than on chronology.

    Scoped to the case paragraph, not the opening: the hypothesis is about how a
    story is told, and a first-person declaration ("我今天突然想分享…") is a
    perfectly good opening that says nothing about case ordering.

    Time-first is the pattern the methodology warns against; a consequence or
    reversal before the time marker is the pattern it recommends.
    """
    compact = re.sub(r"\s", "", text or "")
    if not compact:
        return 0.0
    case_marker = re.compile(
        r"(我有个朋友|我有一个朋友|我认识|有一次|那天|去年冬天|去年|当时|后来我|我妈说|他说|她说)"
    )
    match = case_marker.search(compact)
    if not match:
        return 0.0
    # Read a window from the case marker and decide by order of appearance:
    # a consequence BEFORE the narrative gets going is result-first; a time
    # marker followed by plot with no consequence nearby is chronological.
    window = compact[match.start() : match.start() + 200]
    consequence = re.search(r"(结果|最后|最终|反而|但我|却没有|竟然|才知道|才发现)", window)
    early_time = re.match(r"^(去年|今年|昨天|那天|当时|有一次|小时候|后来)", window)

    if consequence is None:
        return 0.0
    # If the text opens the case on a time marker but the consequence follows
    # within the same window, it is still telling the outcome early enough to
    # create a question. Only a long stretch of plot before any outcome is
    # chronological.
    if early_time and consequence.start() > 80:
        return 0.0
    return 1.0


def detect_mechanism(text: str) -> float:
    """Whether the text explains why, not only what.

    The topic words 心理学 / 认知 used to count as mechanism signals, so
    「今天我想跟大家分享一个心理学的方法」 — which explains nothing — scored as
    an explanation. On the Ego corpus that inflated this rule to 87% support with
    samples like 「我在学心理学之前…」. A mechanism claim needs a causal link, not
    a subject matter.
    """
    compact = re.sub(r"\s", "", text or "")
    hits = sum(
        1
        for pattern in (
            r"因为.{0,40}[。！？]",
            r"之所以.{0,60}",
            r"本质上",
            r"底层逻辑",
            r"机制",
            r"根源",
            r"导致.{0,40}",
            r"这就是为什么",
        )
        if re.search(pattern, compact)
    )
    return min(1.0, hits / 2)


def detect_specific_detail(text: str) -> float:
    """Share of content units carrying a *checkable* point.

    Uses :func:`content_units` so a transcript is measured in sentences rather
    than in 9-character breath lines.

    ``actor`` is deliberately **not** in the concrete set. It used to be, and
    the effect was to measure pronoun density rather than specificity: the
    pattern is ``(我|他|她|我妈|朋友|同事|…)``, so 「我觉得这个就是很大的成长」
    counted as "has a checkable detail". Measured on the 147-post Ego corpus,
    **61% of all units hit on actor alone**, and removing it dropped the score
    from 93.9% to 1.4% — the rule was a pronoun counter.

    The cost is acknowledged: a genuine event statement that names only a person
    ("我妈哭了") no longer counts. That is the safer error — a rule that fires on
    every first-person sentence cannot discriminate at all, and it produced a
    false hard rule that would have been injected into every draft.
    """
    concrete = {"time", "place", "speech", "sensation", "number"}
    units = content_units(text)
    if not units:
        return 0.0
    hits = sum(1 for unit in units if concrete & set(evidence_signals(unit)))
    return hits / len(units)


def detect_quoted_speech(text: str) -> float:
    """Whether the text contains someone's **actual** words.

    Requires quoted content or an explicit ``说：``. Bare 「他说」「她说」 is
    reported speech — it tells you a person spoke, not what they said — and
    counting it made four pronoun-only sentences score 1.0.

    This function had its own pattern while ``writing_signals._SPEECH`` (used by
    ``specific_detail``) had another; only the latter was tightened. Two
    detectors for one concept is how a fix lands in half the system.
    """
    pattern = r"([“\"「].{2,60}[”\"」]|说[:：]\s*\S|告诉我说|原话是|他的原话)"
    return 1.0 if re.search(pattern, text or "") else 0.0


def detect_somatic(text: str) -> float:
    """Bodily detail — the cheapest way to make a claim feel lived."""
    return 1.0 if re.search(r"(脸红|手抖|心跳|胸口|胃|喘不上|呼吸不上|哭|失眠|睡不着|浑身)", text or "") else 0.0


def detect_inventory_format(text: str) -> float:
    """Whether the piece is organised as a numbered/bulleted inventory."""
    hits = len(re.findall(r"^\s*(\d+[.、)]|[①②③④⑤⑥⑦⑧⑨⑩]|[-•●])\s*", text or "", re.M))
    return 1.0 if hits >= 3 else 0.0


def detect_declarative_close(text: str) -> float:
    """Whether the piece lands its last line rather than stopping mid-thought.

    Interpreted as "the final line asserts something", not "the final line is one
    of five known closing templates". Most spoken posts end on a plain assertion
    (「你会变得温柔而有力量」) which no template list catches; requiring a template
    would report 36% support for a convention that actually holds nearly always.

    Two things had to be excluded before this measured anything:

    * Trailing hashtags. A real note ends with ``#AI搞学习howto[话题]# #AI工具[话题]#``
      — a metadata line that never ends on a particle and is always longer than
      six characters. Without stripping it the detector scored 75/75.
    * The title. ``CorpusDoc.text_for_detector`` puts the title first, so once the
      tag lines were dropped the "last line" became the *title* — a complete
      sentence by construction. That is why stripping tags alone still reported
      95.7%. A title is not a closing.
    """
    body = strip_publish_section(text)
    body = _strip_trailing_tags(body)
    # Take the last *semantic* unit, not the last physical line.
    #
    # The line-based version measured the source's formatting rather than the
    # author's closing: a spoken transcript arrives as ~10-char caption lines, so
    # 「你的性魅力」/「也就开始了」 became the "last line" and a complete assertion
    # was rejected as a fragment. Measured: Ego 38% (transcript) vs the same rule
    # on punctuated prose 70% — a formatting artefact, not a style difference.
    #
    # ``content_units`` already decides the right granularity per text (joined
    # breath units for transcripts, sentences for prose), which is why every
    # other detector uses it.
    units = content_units(body)
    if not units:
        return 0.0
    # Walk back past units that are nothing but topic tags. A note often ends
    # with a tag block that has no terminal punctuation, so it becomes the final
    # "sentence"; stripping the tags leaves an empty string and the real closing
    # sits one unit earlier.
    last = ""
    for unit in reversed(units):
        candidate = re.sub(r"\s", "", _INLINE_TAG.sub("", unit).strip())
        if candidate:
            last = candidate
            break
    if not last:
        return 0.0
    # A bare bullet or a lone tag left behind after stripping is not a close.
    if re.fullmatch(r"[•·\-—*#>\[\]（）()a-zA-Z0-9\s]+", last):
        return 0.0
    # Trailing off means the last unit cannot stand alone: it ends on a
    # connective or an adverb that needs a predicate ("我觉得这个就是" /
    # "我现在只想"). Aspect markers 了/着/过 are NOT trailing-off signals — they
    # complete a sentence ("雨停了" / "也就开始了"), and including them rejected
    # most spoken closings.
    if re.search(
        r"(所以|因为|但是|而且|然后|如果|虽然|就是|只是|还是|或者|以及|"
        r"的|把|被|给|就|才|也|还|又|再|很|太|更|最)$",
        last,
    ):
        return 0.0
    # A very short fragment is a breath, not a close.
    if len(last) < 6:
        return 0.0
    # Zero-width characters mean this line is metadata, not prose.
    if re.search(r"[\u200b\u200c\u200d\u2060\ufeff]", last):
        return 0.0
    # Thanks and disclaimers are complete sentences but they are not the
    # author landing a judgement. Without this the detector reported ~91% on the
    # AI corpus, and the "closings" it counted included 「感谢@xxx 的分享」
    # and 「（本视频不含任何平台推荐）」.
    if re.match(r"^(感谢|谢谢|多谢|（本视频|\(本视频|本文|以上|未完)", last):
        return 0.0
    # A CTA is a different closing move (``transactional_cta``), not a
    # declarative close. Without this, 「评论区说说～」 counted as landing a
    # judgement and every post ending in a call to action scored 1.0.
    #
    # Anchored at the start on purpose: 「所以你要先动手，别只是收藏」 *mentions*
    # 收藏 but is an assertion, and the unanchored version rejected it.
    if re.search(r"^(评论区|留言区|收藏一下|关注一下|点赞|转发|私信|扣个?1)", last) or "评论区" in last:
        return 0.0

    # It is not a question — 「是哪一件？」 is asking, not landing.
    if re.search(r"[？?]\s*$", last):
        return 0.0

    # Require an asserting word. This whitelist is a known compromise: it rejects
    # a few genuine closings that happen not to use these words
    # (「后面就好判断」「现在开始干活」). Removing it was tried and made the rule
    # true for 92–93% of *both* corpora — a convention everyone follows cannot
    # distinguish one author from another, and the rule stopped proving anything.
    # Fixing it properly needs a semantic judgement, not a longer word list.
    if not re.search(
        r"(就是|才是|从来|永远|其实|不过|负责|应该|必须|不必|可以|不是|"
        r"更|只|记住|别|尽量|建议|一定|都要|都会|才算|才有|才叫|会)",
        last,
    ):
        return 0.0
    return 1.0


def detect_transactional_cta(text: str) -> float:
    """Whether the close is an operational CTA (collect/comment/follow/DM)."""
    moves = set(closing_moves(text))
    return 1.0 if moves & {"save", "comment", "follow", "private"} else 0.0


def detect_second_person(text: str) -> float:
    """Whether 'you' outnumbers 'I' — a claimed trait in one author's own manual."""
    me = (text or "").count("我")
    you = (text or "").count("你")
    return 1.0 if you > me else 0.0


# --- Hook / layout detectors -------------------------------------------------
# These reuse the signals the 爆文拆解 module already computes (``analyze_hook``),
# so the distiller stops ignoring evidence that is already on hand. Each is
# scoped to the title (see ``_TITLE_DETECTORS``) because that is where a hook
# lives; a rule about "opens with a number" measured on the body would be
# measuring something else.

def _hook_signals(text: str) -> dict[str, Any]:
    """Hook flags from the shared analysis module, title = first line."""
    from backend.app.services.viral_analysis_service import analyze_hook

    return analyze_hook(_title_line(text))


def _title_line(text: str) -> str:
    """Just the title, even though ``text_for_detector`` hands over title+body.

    Title-scoped detectors receive ``"{title}\n{body}"``; measuring the whole
    string would let a body-level reversal satisfy a rule about the title. That
    happened on the first attempt: ``hook_contrast`` reported 93.2%, identical to
    the body-level ``contrast``, because it was reading her paragraphs.
    """
    raw = (text or "").lstrip()
    if not raw:
        return ""
    return raw.splitlines()[0]


# Role markers that name who the piece is about. The shared IDENTITY_MARKERS list
# is creator/e-commerce vocabulary; these cover relationship/psychology tracks
# without pretending the two are the same.
_ROLE_MARKER = re.compile(
    r"(型人|依恋人|伴侣|回避型|焦虑型|安全型|女人|男人|女性|男性|"
    r"母亲|父亲|父母|孩子|朋友|同事|老板|伴侣|"
    r"的人|这些人|那种人|一类人|这种人)"
)


def detect_hook_number(text: str) -> float:
    """Does the title open with a number (a concrete quantity to anchor on)?"""
    try:
        return 1.0 if _hook_signals(text).get("has_number") else 0.0
    except Exception:  # noqa: BLE001 - a broken detector must not kill the run
        return 0.0


def detect_hook_question(text: str) -> float:
    """Does the title ask a question?"""
    try:
        return 1.0 if _hook_signals(text).get("has_question") else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def detect_hook_identity(text: str) -> float:
    """Does the title name an identity the reader can recognise?

    ``viral_analysis.IDENTITY_MARKERS`` is a *creator/e-commerce* vocabulary
    (小白, 打工人, 宝妈, 零基础). Scored against ego's psychology corpus it returns
    0/147 while her titles obviously do address an identity — 「回避型的痛苦」,
    「女人会撒娇」, 「真正掌握主动权的人」. A word list tuned for one track cannot
    measure another, so the shared list is extended with role markers rather than
    trusted alone.
    """
    try:
        from backend.app.services.viral_analysis_service import IDENTITY_MARKERS

        title = _title_line(text)
        if any(word in title for word in IDENTITY_MARKERS):
            return 1.0
        return 1.0 if _ROLE_MARKER.search(title) else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def detect_hook_contrast(text: str) -> float:
    """Does the title set up a reversal?

    Deliberately reuses ``detect_contrast`` rather than
    ``viral_analysis.CONTRAST_PATTERNS``: that list does not know 「不是…而是」
    or 「而非」, so ego's titles — which are built on exactly that structure —
    scored 0% on a rule that is really about their strongest habit.
    """
    try:
        return detect_contrast(_title_line(text))
    except Exception:  # noqa: BLE001
        return 0.0


def detect_hook_emoji(text: str) -> float:
    """Does the title carry an emoji, or none at all?"""
    try:
        return 1.0 if _hook_signals(text).get("emoji_count") else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


# --- Layout detectors --------------------------------------------------------
# Also body-level habits the analysis module already measures. Paragraph rhythm
# is a real authorial fingerprint: ego averages 12 short paragraphs, the AI
# corpus averages 5 longer ones.


def _content_block(text: str) -> str:
    from backend.app.services.writing_signals import strip_publish_section

    return strip_publish_section(text) or ""


def detect_paragraph_rhythm(text: str) -> float:
    """Does the piece break into many short units (a scannable rhythm)?

    Measured in ``content_units``, not raw lines. A spoken transcript arrives as
    ~130 caption lines of 10 chars each; counting those as "many short
    paragraphs" would score 1.0 for every transcript regardless of the author.
    Joined into breath units, ego averages ~29 units of ~43 chars — a real,
    measurable rhythm that the raw-line version could not see.

    Shorter pieces fail the "10 units" half of the rule. That is a real limit of
    the rule, not of the author: a 40-second Douyin clip cannot contain ten
    40-character units, so this hypothesis stays unproven on short-video corpora
    (and it carries no counter_rule, so it never becomes an instruction).
    """
    from backend.app.services.writing_signals import content_units

    body = _content_block(text)
    units = content_units(body)
    if not units:
        return 0.0
    avg = sum(len(unit) for unit in units) / len(units)
    return 1.0 if avg <= 50 and len(units) >= 10 else 0.0


def detect_emoji_use(text: str) -> float:
    """Does the body use emoji as structure (bullets/markers), not decoration?"""
    from backend.app.services.viral_analysis_service import EMOJI_PATTERN

    body = _content_block(text)
    if not body:
        return 0.0
    hits = len(EMOJI_PATTERN.findall(body))
    # Density, not presence: one emoji in 1000 chars is decoration.
    return 1.0 if hits and hits / max(len(body), 1) * 200 >= 1 else 0.0


def detect_bullet_layout(text: str) -> float:
    """Does the body lean on bullets/lists rather than continuous prose?"""
    body = _content_block(text)
    if not body:
        return 0.0
    bullets = len(re.findall(r"^\s*(\d+[.、)]|[①②③④⑤⑥⑦⑧⑨⑩]|[-•●▪◦])\s*", body, re.M))
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        return 0.0
    return 1.0 if bullets >= 3 and bullets / len(lines) >= 0.15 else 0.0



DETECTORS: dict[str, Callable[[str], float]] = {
    "short_units": detect_short_units,
    "contrast": detect_contrast,
    "result_first": detect_result_first,
    "mechanism": detect_mechanism,
    "specific_detail": detect_specific_detail,
    "quoted_speech": detect_quoted_speech,
    "somatic": detect_somatic,
    "inventory_format": detect_inventory_format,
    "declarative_close": detect_declarative_close,
    "transactional_cta": detect_transactional_cta,
    "second_person": detect_second_person,
    # Hook signals — reuse 爆文拆解's analyze_hook instead of recomputing.
    "hook_number": detect_hook_number,
    "hook_question": detect_hook_question,
    "hook_identity": detect_hook_identity,
    "hook_contrast": detect_hook_contrast,
    "hook_emoji": detect_hook_emoji,
    # Layout signals — the analysis module measures these too.
    "paragraph_rhythm": detect_paragraph_rhythm,
    "emoji_use": detect_emoji_use,
    "bullet_layout": detect_bullet_layout,
}


# --- Library ----------------------------------------------------------------
# Ordered by how much they should drive writing: structure before decoration.

HYPOTHESES: tuple[Hypothesis, ...] = (
    Hypothesis(
        key="result_first",
        claim="案例先给结果，再讲过程；按时间顺序平铺直叙会丢掉悬念。",
        source="theory",
        dimension="结构",
        detector="result_first",
        rule="写案例时第一句先给反常结果或代价，再回头讲过程；不要从时间线开头。",
        counter_rule="",
        note="叙事学中的「时距」操作：把结果前置相当于压缩过程、拉伸瞬间。",
        tags=("narrative", "structure"),
    ),
    Hypothesis(
        key="contrast",
        claim="反认知/转折句式（不是X而是Y）是中文内容里最高效的注意力装置。",
        source="theory",
        dimension="表达",
        detector="contrast",
        rule="每篇至少出现一次明确反转：先承认大众说法，再给出自己的判断。",
        counter_rule="该题材几乎不用反转，改用直接结论或具体场景开头。",
        note="期待违背（expectancy violation）：先建立预期，再打破。",
        tags=("rhetoric",),
    ),
    Hypothesis(
        key="specific_detail",
        claim="可核验的细节（时间/当事人/原话/身体感受）比形容词更能建立可信度。",
        source="theory",
        dimension="证据",
        detector="specific_detail",
        rule="每个关键判断配一个具体细节，不接受只有结论的段落。",
        note="具体性效应：具体陈述比抽象陈述更容易被记住和相信。",
        tags=("evidence",),
    ),
    Hypothesis(
        key="mechanism",
        claim="给出机制（为什么会这样）的内容更容易被收藏，而不是只被看完。",
        source="theory",
        dimension="深度",
        detector="mechanism",
        rule="在故事之后补一层解释：为什么会这样、底层是什么。",
        note="收藏动机来自「以后可能用到」，机制是可用性的来源。",
        tags=("depth",),
    ),
    Hypothesis(
        key="short_units",
        claim="口播/图文都用短意群推进，单句过长会掉完播。",
        source="corpus",
        dimension="节奏",
        detector="short_units",
        rule="单句控制在一个呼吸内，长句拆开。",
        note="该参数来自具体语料，换题材必须重测。",
        tags=("rhythm",),
    ),
    Hypothesis(
        key="quoted_speech",
        claim="直接引语比转述更有现场感。",
        source="theory",
        dimension="证据",
        detector="quoted_speech",
        rule="关键冲突用对话呈现，不要只写「他说了一些难听的话」。",
        tags=("evidence",),
    ),
    Hypothesis(
        key="somatic",
        claim="身体感受是最难编造、也最容易被共情的细节。",
        source="theory",
        dimension="证据",
        detector="somatic",
        rule="写到情绪时给一个身体反应，而不是只写「我很难过」。",
        tags=("evidence",),
    ),
    Hypothesis(
        key="declarative_close",
        claim="结尾落在完整判断上（金句/许可/下一步）比落在半句上更完整。",
        source="theory",
        dimension="收尾",
        detector="declarative_close",
        rule="结尾给一句能独立传播的判断，或一个具体下一步。",
        tags=("closing",),
    ),
    Hypothesis(
        key="transactional_cta",
        claim="运营型 CTA（收藏/评论/关注）是可选手段，不是好结尾的必要条件。",
        source="corpus",
        dimension="收尾",
        detector="transactional_cta",
        rule="只有在需要转化时才加运营 CTA；叙事型内容可以只收在金句上。",
        note="运营 CTA 是运营动作，不是写作风格：报告只记录它是否出现在结尾。",
        tags=("closing",),
    ),
    Hypothesis(
        key="second_person",
        claim="「你」多于「我」会让内容更像对话。",
        source="corpus",
        dimension="人称",
        detector="second_person",
        rule="说话对象明确时多用「你」。",
        counter_rule="作者本人就是主角，第一人称占比更高；不要为了对话感硬塞「你」。",
        note="方法论自称高频用「你」；是否成立只看这份语料的覆盖率，不看自述。",
        tags=("voice",),
    ),
    Hypothesis(
        key="inventory_format",
        claim="清单式结构（编号/要点）适合工具与方法题材，不适合叙事。",
        source="theory",
        dimension="结构",
        detector="inventory_format",
        rule="方法类内容用编号清单；叙事类不要硬拆清单。",
        tags=("structure", "format"),
    ),
    # --- Hook dimension -----------------------------------------------------
    # ego's own manual has a whole chapter「开头钩子库（X 种高转化模式）」. These
    # four rules are the measurable part of it: does the author habitually reach
    # for a number / question / identity / reversal in the title.
    Hypothesis(
        key="hook_number",
        claim="标题里带具体数字，给读者一个可抓住的量。",
        source="theory",
        dimension="钩子",
        detector="hook_number",
        rule="标题带一个具体数字（几个工具、几天、多少钱），不要写「很多」「一些」。",
        counter_rule="这个作者不靠数字起标题，别硬塞；用她习惯的钩子类型。",
        note="具体性效应：可核验的量比形容词更容易被记住。",
        tags=("hook", "title"),
    ),
    Hypothesis(
        key="hook_question",
        claim="用疑问句把读者拉进对话，而不是直接下结论。",
        source="theory",
        dimension="钩子",
        detector="hook_question",
        rule="标题可以是疑问句，但要问读者真正在纠结的问题，不要设问后自问自答。",
        counter_rule="",
        note="疑问句制造「未完成感」，读者会想补上答案。",
        tags=("hook", "title"),
    ),
    Hypothesis(
        key="hook_identity",
        claim="标题点名一个身份（打工人 / 宝妈 / 一人公司），让对应的人立刻对号入座。",
        source="theory",
        dimension="钩子",
        detector="hook_identity",
        rule="标题里放一个读者认得出的身份标签。",
        counter_rule="",
        note="身份标签是筛选器：不相关的人划走，相关的人停下。",
        tags=("hook", "title"),
    ),
    Hypothesis(
        key="hook_contrast",
        claim="标题先立一个大众说法，再暗示它不成立。",
        source="theory",
        dimension="钩子",
        detector="hook_contrast",
        rule="标题用「不是A而是B」「你以为…其实」这类反转结构。",
        counter_rule="",
        note="期待违背：先建立预期再打破，注意力成本最低。",
        tags=("hook", "title"),
    ),
    Hypothesis(
        key="hook_emoji",
        claim="标题带一个 emoji，在信息流里制造视觉停顿。",
        source="theory",
        dimension="钩子",
        detector="hook_emoji",
        rule="标题可以带 1 个 emoji 做视觉锚点，不要堆三个以上。",
        counter_rule="这个作者的标题不用 emoji，跟着她的习惯来。",
        note="",
        tags=("hook", "title"),
    ),
    # --- Layout dimension ----------------------------------------------------
    Hypothesis(
        key="paragraph_rhythm",
        claim="正文切成多段短段，手机上滑一遍就能看完。",
        source="theory",
        dimension="排版",
        detector="paragraph_rhythm",
        rule=(
            "正文切成 10 个以上内容单元，平均每单元不超过 50 字"
            "（本语料中位 {median} 个，10–90 分位 {p10}–{p90}，别切成几十个碎片）。"
        ),
        counter_rule="",
        note="移动端阅读：段落是呼吸单位，不是逻辑单位。",
        tags=("layout",),
    ),
    Hypothesis(
        key="emoji_use",
        claim="用 emoji 当结构标记（分段/强调），而不是装饰。",
        source="theory",
        dimension="排版",
        detector="emoji_use",
        rule="需要分段或强调时用 1 个 emoji 做标记，不要每句都加。",
        counter_rule=(
            "正文不要使用任何 emoji（这个作者绝大多数稿子正文里一个都没有），保持纯文字。"
        ),
        note="",
        tags=("layout",),
    ),
    Hypothesis(
        key="bullet_layout",
        claim="方法类内容用编号清单承载，不堆成连续段落。",
        source="theory",
        dimension="排版",
        detector="bullet_layout",
        rule="列方法/步骤时用编号或圆点，每条一行。",
        counter_rule="",
        note="",
        tags=("layout",),
    ),

)

HYPOTHESIS_BY_KEY: dict[str, Hypothesis] = {item.key: item for item in HYPOTHESES}


def hypotheses_for(tags: tuple[str, ...] | list[str] | None = None) -> list[Hypothesis]:
    """All hypotheses, or those sharing at least one tag."""
    if not tags:
        return list(HYPOTHESES)
    wanted = set(tags)
    return [item for item in HYPOTHESES if wanted & set(item.tags)]


def serialize_hypotheses(items: list[Hypothesis] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "key": item.key,
            "claim": item.claim,
            "source": item.source,
            "dimension": item.dimension,
            "detector": item.detector,
            "rule": item.rule,
            "counter_rule": item.counter_rule,
            "note": item.note,
            "tags": list(item.tags),
        }
        for item in (items if items is not None else HYPOTHESES)
    ]


__all__ = [
    "Hypothesis",
    "HYPOTHESES",
    "HYPOTHESIS_BY_KEY",
    "DETECTORS",
    "hypotheses_for",
    "serialize_hypotheses",
]
