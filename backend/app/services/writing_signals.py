"""Evidence and information-point detection shared by both scorers.

The old implementation treated "evidence" as money, hours, screenshots, and
treated "information density" as character count. Both proxies fail on writing
where the proof is relational rather than commercial:

    「去年冬天我和当时的伴侣爆发过一次巨大冲突，他用了很难听的话攻击我。
      但我最后没有骂回去，反而看见了他的脆弱。」

That sentence carries four verifiable information points and zero of the words
the old rule looked for. Measured on the ego corpus (154 posts), the old CTA
rule scored that style 0.0/10 while scoring generic filler 3.5/10 — the scorer
was rewarding the writing the user most wanted to avoid.

This module separates the two questions the old code conflated:

* ``evidence_points`` — is there something specific the reader can check?
  Numbers, time, place, named actors, quoted speech, bodily sensation, a
  before/after contrast, a cited mechanism.
* ``information_density`` — how many of those points does each sentence add?
  A 300-character post repeating one vague claim is not dense; a 300-character
  post with six concrete beats is.

Both are deliberately conservative: they count what is visibly present and
never infer. A missing signal lowers the score; it is not replaced with
"probably fine", which is the failure mode this whole exercise is about.
"""
from __future__ import annotations

import re
from typing import Any

# --- Signals -----------------------------------------------------------------

# Concrete, checkable specifics. Each pattern is one kind of evidence; a sentence
# may carry several.
_NUMBER = re.compile(r"\d")
_TIME = re.compile(
    r"(今天|明天|昨天|前天|昨晚|今晚|今年|去年|上个月|上周|"
    r"早上|上午|中午|下午|晚上|刚才|当时|那天|有一次|第一次|后来|小时候|"
    r"\d+\s*(年|月|天|小时|分钟|块|元|岁))"
)
_PLACE = re.compile(r"(公司|会议|学校|医院|地铁|家里|餐厅|咖啡馆|办公室|现场|群里|评论区)")
_ACTOR = re.compile(r"(我|他|她|我妈|我爸|朋友|同事|领导|客户|学员|伴侣|男朋友|女朋友|孩子)")
_SPEECH = re.compile(
    r"([“\"「].{2,40}[”\"」]|说[:：]|告诉我说|原话是|他的原话)"
)
_SENSATION = re.compile(
    r"(脸红|手抖|发抖|心跳|胸口|胃|喘不上|呼吸不上|哭|失眠|睡不着|浑身|"
    r"冒汗|出汗|手心全是汗|头皮发麻)"
)
_CONTRAST = re.compile(r"(不是.{0,25}?而是|反而|却|其实|表面上|看起来.{0,20}?实际上)")
_MECHANISM = re.compile(r"(心理学|本质上|底层逻辑|机制|因为|导致|根源|创伤|依恋|边界|潜意识|投射|认知)")
_CONSEQUENCE = re.compile(r"(结果|最终|最后|于是|所以|导致|变成|成了)")

EVIDENCE_SIGNALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("number", _NUMBER),
    ("time", _TIME),
    ("place", _PLACE),
    ("actor", _ACTOR),
    ("speech", _SPEECH),
    ("sensation", _SENSATION),
    ("contrast", _CONTRAST),
    ("mechanism", _MECHANISM),
    ("consequence", _CONSEQUENCE),
)

# Words that make a claim but carry no evidence. Presence is not penalised on its
# own — vague advice is simply low-density, not "wrong".
GENERIC_MARKERS = (
    "很多人", "大家都知道", "众所周知", "其实不难", "关键在于", "要注意",
    "很重要", "坚持下去", "一定会有收获", "希望对你有帮助", "加油",
)

# Operations-style CTAs. Kept for prompts that genuinely want a sales close, but
# no longer the only way to earn a CTA point (see closing move detection).
OPERATION_CTAS: dict[str, tuple[str, ...]] = {
    "save": ("收藏", "码住", "先收藏"),
    "comment": ("评论", "留言", "告诉我", "你们觉得", "欢迎讨论"),
    "follow": ("关注", "点个关注", "记得关注"),
    "private": ("私信", "私我", "后台回复", "报名", "滴滴"),
}

# Non-transactional closings. Writing that ends on a thought, a permission, or a
# concrete next action still "closes"; scoring it zero taught the model that the
# only valid ending is a sales line.
_CLOSING_MOVES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aphorism", re.compile(r"(就是|才是|从来|永远|其实|不过是|从来不是).{0,24}[。！]?\s*$")),
    ("permission", re.compile(r"(你可以|你不必|你不需要|允许自己|不用急着|慢一点)")),
    ("next_action", re.compile(r"(下一次|下次|从今天|以后|当你|如果.{0,12}就)")),
    ("question", re.compile(r"[？?]\s*$")),
    ("invitation", re.compile(r"(我想邀请你|邀请你|试着|不妨)")),
)


def split_sentences(text: str) -> list[str]:
    """Split into sentences, keeping it usable for both prose and transcripts.

    Transcripts have no punctuation and use line breaks as breath units, so a
    pure ``[。！？]`` split would return one giant "sentence" for a 1,300-char
    spoken post and make every density ratio meaningless.
    """
    if not text:
        return []
    chunks = re.split(r"[。！？!?；;\n]+", text)
    return [chunk.strip() for chunk in chunks if chunk and chunk.strip()]


def evidence_signals(sentence: str) -> list[str]:
    """Which kinds of evidence appear in one sentence. Empty list = no evidence."""
    return [name for name, pattern in EVIDENCE_SIGNALS if pattern.search(sentence)]


def evidence_points(text: str) -> int:
    """Count distinct evidence-bearing sentences.

    Distinct *sentences*, not distinct patterns: one sentence that mentions a
    time, a person and a quote is one beat of a story, not three.
    """
    return sum(1 for sentence in split_sentences(text) if evidence_signals(sentence))


def information_density(text: str) -> float:
    """Share of sentences that add a checkable point (0.0 – 1.0).

    Ratio rather than raw count so length alone cannot raise the score. A short
    post where every sentence is concrete scores higher than a long post that
    circles one vague claim.
    """
    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    with_evidence = sum(1 for sentence in sentences if evidence_signals(sentence))
    return with_evidence / len(sentences)


def generic_ratio(text: str) -> float:
    """Share of sentences that are generic advice with no specifics."""
    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    generic = sum(
        1
        for sentence in sentences
        if any(marker in sentence for marker in GENERIC_MARKERS) and not evidence_signals(sentence)
    )
    return generic / len(sentences)


def strip_publish_section(text: str) -> str:
    """Keep only the spoken part.

    The corpus format is::

        口播转写全文……
        （空行）
        【发布正文】
        标题 #标签 #标签

    Scoring the whole block counts the publish line twice (as body) and makes the
    closing look like a hashtag list. The spoken part is what a transcript can
    be judged on; the publish line is metadata.
    """
    marker = "【发布正文】"
    if marker in (text or ""):
        return (text or "").split(marker)[0].strip()
    return (text or "").strip()


def _is_tag_line(line: str) -> bool:
    """A metadata line made only of hashtags, possibly with stray whitespace.

    The old test was ``count("#") >= 2``, which let a single-tag line through:
    ``#AI[话题]`` then became the "last line" and scored as a declarative close
    because it is longer than six characters and ends on ``]``.

    Zero-width characters are stripped first. XHS bodies contain ``\\u200b`` and
    ``\\u2060`` between tags; they are not whitespace, so a line made only of tags
    failed the "leftover is punctuation" test and survived.
    """
    stripped = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", (line or "")).strip()
    if not stripped or "#" not in stripped:
        return False
    # Remove every hashtag token; whatever is left must be punctuation only.
    remainder = re.sub(r"#[^#\s]*", "", stripped)
    return len(remainder.strip()) <= 1


def _strip_trailing_tags(text: str) -> str:
    """Drop trailing hashtag-only lines before looking at the close."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    while lines and _is_tag_line(lines[-1]):
        lines.pop()
    return "\n".join(lines)


def closing_moves(text: str) -> list[str]:
    """How the piece ends: operation CTA, aphorism, permission, next action...

    Returns every move that matches, so a piece that both gives a next action and
    lands a line is credited for both rather than being forced into one bucket.
    """
    body = strip_publish_section(text)
    tail = "\n".join(_strip_trailing_tags(body).strip().splitlines()[-2:]).strip()
    if not tail:
        return []
    moves = [name for name, words in OPERATION_CTAS.items() if any(word in tail for word in words)]
    moves += [name for name, pattern in _CLOSING_MOVES if pattern.search(tail)]
    # A closing declaration in any form ("爱，是看见。") is still a closing move.
    # Drafts normally end with punctuation; transcripts split on line breaks and
    # often do not, so also accept a final line that reads as complete.
    #
    # Deliberately narrow: a single short sentence with no closing signal is not
    # a close. Otherwise "一段没有互动引导的正文" would earn CTA points for
    # merely existing, which is the "looks fine, proves nothing" failure again.
    if not moves and tail:
        lines = [line.strip() for line in _strip_trailing_tags(body).splitlines() if line.strip()]
        last = lines[-1] if lines else ""
        trails_off = re.search(r"[，,、和而但就也因为所以如果当的]$", last)
        # A closing declaration in any form ("爱，是看见。") is still a close.
        # Requires a complete assertion: either it ends with punctuation in a
        # piece that has structure, or the line asserts something on its own.
        assertable = bool(
            re.search(r"(就是|才是|从来|永远|其实|不过|负责|应该|必须|不必|可以|不是|更|只)", last)
        )
        has_structure = len(lines) >= 2 or len(re.sub(r"\s", "", body or "")) >= 120
        if not trails_off and (
            (re.search(r"[。！？!?…]$", last) and (has_structure or assertable))
            or (assertable and len(last) >= 6)
        ):
            moves.append("declarative")
    return list(dict.fromkeys(moves))


def describe_evidence(text: str, limit: int = 3) -> list[str]:
    """Short human-readable evidence samples, for advice text and debugging."""
    samples: list[str] = []
    for sentence in split_sentences(text):
        signals = evidence_signals(sentence)
        if signals:
            samples.append(f"{sentence[:40]}（{'/'.join(signals)}）")
        if len(samples) >= limit:
            break
    return samples


def score_summary(text: str) -> dict[str, Any]:
    """Bundled metrics, used by tests and by the advice strings."""
    return {
        "sentences": len(split_sentences(text)),
        "evidence_points": evidence_points(text),
        "information_density": round(information_density(text), 3),
        "generic_ratio": round(generic_ratio(text), 3),
        "closing_moves": closing_moves(text),
    }


def join_breath_units(text: str, max_chars: int = 40) -> list[str]:
    """Re-join transcript breath units into sentences.

    Spoken transcripts are broken at breath, not at punctuation: a 1,300-char
    post arrives as ~130 lines averaging 9 characters. Measuring "does this unit
    carry a checkable detail" per line therefore reports ~0.49 for writing that
    actually scores 0.87 once lines are joined back into sentences. The unit of
    measurement was wrong, not the writing.
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    units: list[str] = []
    buffer = ""
    for line in lines:
        buffer = f"{buffer}{line}" if buffer else line
        if re.search(r"[。！？!?；;,，]$", line) or len(re.sub(r"\s", "", buffer)) >= max_chars:
            units.append(buffer)
            buffer = ""
    if buffer:
        units.append(buffer)
    return units


def content_units(text: str) -> list[str]:
    """Sentences when the text is punctuated, joined breath units when it is not.

    Picks by punctuation density, not by comparing average lengths: both
    :func:`split_sentences` and a transcript split on newlines produce
    line-length units, so a length comparison cannot tell them apart (measured:
    it silently returned the raw lines and kept the 0.49 score).

    A transcript has many line breaks and almost no sentence-final marks.
    """
    raw = text or ""
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return []
    terminal_marks = len(re.findall(r"[。！？!?]", raw))
    # Punctuated prose averages roughly one terminal mark per 1-3 lines.
    if terminal_marks * 3 >= len(lines):
        return split_sentences(raw)
    return join_breath_units(raw)


__all__ = [
    "EVIDENCE_SIGNALS",
    "GENERIC_MARKERS",
    "OPERATION_CTAS",
    "split_sentences",
    "join_breath_units",
    "content_units",
    "strip_publish_section",
    "evidence_signals",
    "evidence_points",
    "information_density",
    "generic_ratio",
    "closing_moves",
    "describe_evidence",
    "score_summary",
]
