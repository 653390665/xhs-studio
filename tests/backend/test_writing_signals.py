"""写作信号：证据点、信息密度、收尾动作。

These tests exist because the previous scorers used proxies that silently
rewarded the wrong writing:

* evidence = 元/小时/截图  → a relational story scored 0.30, name-dropping
  "成本" scored 0.65
* information density = character count → 300 chars of filler scored full marks
* CTA = 收藏/评论/关注/私信 → 结尾金句 scored 0.0

Each test below pins one measured behaviour from the ego corpus (154 posts) so a
future refactor cannot quietly reintroduce the old proxy.
"""

from __future__ import annotations

from backend.app.services.content_scoring_service import score_note
from backend.app.services.skill_score_service import _craft
from backend.app.services.writing_signals import (
    closing_moves,
    evidence_points,
    generic_ratio,
    information_density,
    split_sentences,
    strip_publish_section,
)

CONCRETE = """我今天想讲一个可能和全网都对抗的观点：你反复受同一种伤，不是运气差，是你主动选了这个情境。
去年冬天我和当时的伴侣爆发过一次巨大冲突，他用了很难听的话攻击我。但我最后没有骂回去，反而看见了他的脆弱。
为什么？心理学里有个词叫边界。人和人的相处，本质上是两个触角在互相试探边界在哪里。
因为让你痛苦的不是行为本身，是你允许了这个行为。行为是事实，痛苦是你的解释。
所以下次对方再不回应你，你可以直接说：你这样一整天不回我，我会没有安全感。"""

VAGUE = """做自媒体，很多人都会遇到问题。其实这个问题并不难，关键在于你要找到适合自己的方法。
首先要明确目标，知道自己想要什么。其次要坚持执行，不能三天打鱼两天晒网。第三要学会复盘。
很多人之所以做不起来，是因为没有坚持。只要你坚持下去，一定会有收获。
最后，希望这篇内容对你有帮助。你还有什么想法？欢迎在评论区告诉我。"""

TITLE = "为什么你总是遇到同一种人"
TAGS = ["情绪", "亲密关系", "女性成长"]


# --- 信号本身 ---------------------------------------------------------------


def test_concrete_writing_has_more_evidence_than_vague_writing():
    assert evidence_points(CONCRETE) > evidence_points(VAGUE)


def test_information_density_is_a_ratio_not_a_length():
    """Both texts are roughly the same length; only one carries specifics."""
    assert len(CONCRETE) > 0 and len(VAGUE) > 0
    assert information_density(CONCRETE) > information_density(VAGUE)
    assert information_density(VAGUE) < 0.5


def test_generic_ratio_flags_vague_advice():
    assert generic_ratio(VAGUE) > generic_ratio(CONCRETE)
    assert generic_ratio(CONCRETE) == 0.0


def test_transcript_without_punctuation_still_splits():
    """A spoken transcript uses line breaks as breath units, not punctuation."""
    spoken = "我今天突然想分享\n就是你怎么看出自己的创伤\n后来我跟我妈聊了"
    assert len(split_sentences(spoken)) == 3


# --- 收尾动作 ---------------------------------------------------------------


def test_aphorism_ending_counts_as_a_closing_move():
    """「我永远忠诚于我自己」is a valid close; the old rule scored it 0."""
    assert closing_moves("……所以，我永远忠诚于我自己。")


def test_operation_cta_still_counts():
    assert "save" in closing_moves("先收藏，需要哪个再去装哪个。")


def test_trailing_hashtag_line_is_not_the_ending():
    text = "边界意识的核心是，谁的感受谁负责。\n#情感 #心理学 #女性成长"
    moves = closing_moves(text)
    assert moves, "the hashtag line must not hide the real closing"
    assert "save" not in moves


def test_publish_section_is_stripped_from_transcripts():
    raw = "口播正文在这里。\n\n【发布正文】\n标题 #情感 #心理"
    assert strip_publish_section(raw) == "口播正文在这里。"


# --- 两个评分器 -------------------------------------------------------------


def test_craft_prefers_concrete_over_vague():
    """Measured before the fix: 废话 65.7 > ego 61.4. That ordering was wrong."""
    concrete = _craft(TITLE, CONCRETE, TAGS, "long_text", image_count=3, media_known=True, has_video=False)
    vague = _craft(TITLE, VAGUE, TAGS, "long_text", image_count=3, media_known=True, has_video=False)

    assert concrete["total"] > vague["total"]


def test_score_note_prefers_concrete_over_vague():
    concrete = score_note(TITLE, CONCRETE, TAGS)
    vague = score_note(TITLE, VAGUE, TAGS)
    total_concrete = sum(d["score"] for d in concrete["dimensions"])
    total_vague = sum(d["score"] for d in vague["dimensions"])

    assert total_concrete > total_vague


def test_cta_dimension_no_longer_zeroes_a_quotable_ending():
    result = _craft(TITLE, CONCRETE, TAGS, "long_text", image_count=3, media_known=True, has_video=False)
    cta = next(d for d in result["dimensions"] if d["key"] == "cta")
    assert cta["score"] > 0, "结尾金句 must not score 0"


def test_evidence_dimension_prefers_the_relational_story():
    concrete = _craft(TITLE, CONCRETE, TAGS, "long_text", image_count=3, media_known=True, has_video=False)
    vague = _craft(TITLE, VAGUE, TAGS, "long_text", image_count=3, media_known=True, has_video=False)
    ev_concrete = next(d for d in concrete["dimensions"] if d["key"] == "evidence")
    ev_vague = next(d for d in vague["dimensions"] if d["key"] == "evidence")

    assert ev_concrete["score"] > ev_vague["score"]


def test_reversal_title_is_detected():
    """「反复爱上同一种人，不是宿命，是创伤」was scored as having no hook.

    The old regex only matched 「不是……而是……」, while the more common spoken
    form is 「不是X，是Y」.
    """
    from backend.app.services.skill_score_service import _title_ratio

    reversal, _ = _title_ratio("反复爱上同一种人，不是宿命，是创伤")
    plain, _ = _title_ratio("今天聊聊我的想法")

    assert reversal > plain
    assert reversal >= 0.5
