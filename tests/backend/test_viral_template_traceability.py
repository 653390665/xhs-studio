"""A viral template must be traceable to analyses that actually happened.

Three defects were fixed on 2026-10-28:

1. ``recommendations`` were four constant strings, identical for every template.
   One of them said「标题优先测试数字钩子」for a template whose source titles
   almost never contained a digit. Advice that cannot be traced to the data is
   indistinguishable from a guess.

2. ``create_viral_template`` recomputed the analysis inline and never read
   ``viral_analyses``, so a template could be built from notes nobody had ever
   decomposed — while the decompositions that *were* saved went unused.

3. Re-analysing the same note appended a new row every time. One 107-like note
   accumulated 9 identical analyses.
"""

from __future__ import annotations

from backend.app.services.viral_analysis_service import (
    build_viral_template,
    _derive_recommendations,
)


def _note(title="标题", content="正文内容，用来测试。", likes=1000, collects=900,
          comments=10, fans=1000):
    return {
        "note_id": "n1",
        "title": title,
        "content": content,
        "author_name": "作者",
        "author_id": "a1",
        "author_fans": fans,
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "shares": 0,
        "type": "normal",
        "image_count": 1,
    }


def _analysis(likes=1000, collects=900, comments=10, score=50):
    return {
        "engagement": {
            "likes": likes,
            "collects": collects,
            "comments": comments,
            "shares": 0,
            "total_engagement": likes + collects + comments,
        },
        "scoring": {"score": score, "level": "C", "components": {}},
        "hook": {"hook_patterns": []},
        "content": {"hashtags": [], "body_length": 10},
    }


# --- recommendations must follow the source data ---------------------------


def test_recommendations_are_not_constant():
    """Two different corpora must produce different advice."""
    a = build_viral_template([_note(title="3 个方法")], [_analysis()])
    b = build_viral_template(
        [_note(title="聊聊这件事", content="", likes=0, collects=0, comments=2)],
        [_analysis(likes=0, collects=0, comments=2)],
    )

    assert a["recommendations"] != b["recommendations"]


def test_number_advice_matches_the_actual_titles():
    """If no title has a digit, do not tell the user to lead with digits."""
    notes = [_note(title="聊聊独立开发者"), _note(title="一人公司的门槛")]
    analyses = [_analysis(), _analysis()]
    template = build_viral_template(notes, analyses)

    joined = "\n".join(template["recommendations"])
    assert "数字钩子" not in joined or "0/2" in joined
    assert "0/2" in joined


def test_body_length_advice_reports_the_real_spread():
    notes = [_note(content="x" * 500), _note(content="x" * 100)]
    template = build_viral_template(notes, [_analysis(), _analysis()])

    joined = "\n".join(template["recommendations"])
    assert "300" not in joined or "中位" in joined
    # Median of [100, 500] is 500 (upper middle), and the spread is reported.
    assert "100" in joined and "500" in joined


def test_small_like_samples_do_not_produce_confident_engagement_advice():
    """0 likes and 2 comments must not read as 「comment/like = very high」."""
    notes = [_note(likes=0, collects=0, comments=2, content="x" * 200)]
    analyses = [_analysis(likes=0, collects=0, comments=2)]
    template = build_viral_template(notes, analyses)

    joined = "\n".join(template["recommendations"])
    assert "不足以分析互动结构" in joined


def test_weak_samples_are_called_weak():
    """A template built on non-viral samples must say so, and say why."""
    notes = [_note(likes=3, collects=0, comments=1, content="x" * 200)]
    analyses = [_analysis(likes=3, collects=0, comments=1)]
    template = build_viral_template(notes, analyses)

    joined = "\n".join(template["recommendations"])
    assert "不是爆款样本" in joined


def test_strong_samples_are_not_warned_about():
    notes = [_note(likes=50000, collects=60000, comments=500)]
    analyses = [_analysis(likes=50000, collects=60000, comments=500, score=80)]
    template = build_viral_template(notes, analyses)

    joined = "\n".join(template["recommendations"])
    assert "不是爆款样本" not in joined
    assert "不足以分析互动结构" not in joined


def test_recommendations_survive_empty_corpus():
    assert _derive_recommendations([], [], []) == []


# --- structure must vary with the source -----------------------------------


def test_structure_differs_between_different_shapes():
    """The old hard-coded list made every template structurally identical."""
    chatty = [
        _note(content="第一段。\n第二段。\n第三段。\n第四段。\n第五段。"),
        _note(content="开头。\n中间。\n结尾。"),
    ]
    single = [_note(content="就一段话，没有分段。"), _note(content="也是单段。")]

    a = build_viral_template(chatty, [_analysis(), _analysis()])
    b = build_viral_template(single, [_analysis(), _analysis()])

    assert a["structure"] != b["structure"]


# --- the score is not a quality gate --------------------------------------


def test_score_is_labelled_as_relative_not_absolute():
    """Cross-author samples have no baseline, so a 76k-like post scores C.

    The recommendations must therefore judge sample quality by absolute
    engagement, not by score.
    """
    big = _note(likes=76000, collects=100000, comments=339)
    template = build_viral_template([big], [_analysis(likes=76000, collects=100000,
                                                      comments=339, score=37)])

    joined = "\n".join(template["recommendations"])
    assert "不是爆款样本" not in joined, "76000 赞不能被标成非爆款"


# --- sample size ---------------------------------------------------------


def test_template_accepts_more_than_three_notes():
    """A genre claim needs more than three posts.

    The old cap of 3 was the reason a 76000-like post and a 3481-like post
    produced the same "structure": one outlier dominated every ratio.
    """
    from backend.app.api.platforms.xhs.insights import ViralTemplateRequest

    field = ViralTemplateRequest.model_fields["note_ids"]
    assert field.metadata, "note_ids 应该有长度约束"
    # 30 is the current cap; the important part is that it is far above 3.
    assert any(getattr(m, "max_length", 0) >= 10 for m in field.metadata), (
        "模板至少要能装下 10 篇样本，否则统计没有代表性"
    )


def test_more_samples_produce_stable_ratios():
    """With 8 samples the collect ratio should not be dominated by one post."""
    notes = [
        _note(likes=1000, collects=1000),   # 1.0
        _note(likes=1000, collects=1200),   # 1.2
        _note(likes=1000, collects=900),    # 0.9
        _note(likes=1000, collects=1100),   # 1.1
    ]
    analyses = [
        _analysis(likes=1000, collects=1000),
        _analysis(likes=1000, collects=1200),
        _analysis(likes=1000, collects=900),
        _analysis(likes=1000, collects=1100),
    ]
    template = build_viral_template(notes, analyses)

    joined = "\n".join(template["recommendations"])
    # Aggregate ratio is (1000+1200+900+1100)/(4*1000) = 1.05
    assert "1.05" in joined
